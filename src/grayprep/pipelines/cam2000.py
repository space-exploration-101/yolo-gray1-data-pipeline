"""FPGA camera-input preprocessing and the fixed 2000x2000 packed-u12 ABI."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from grayprep.pipelines.common import (
    PreprocessError,
    atomic_write_bytes,
    resize_gray1,
    to_gray1,
)


PACKING_ID = "u12_pair_3byte_p0lo_p0hi-p1lo_p1hi"
BYTE_ORDER_ID = "custom_nibble_packed"
U8_TO_U12_ID = "round(v*4095/255)"


@dataclass(frozen=True)
class Cam2000Spec:
    """Frozen camera binary contract supplied for FPGA board-test inputs."""

    width: int = 2000
    height: int = 2000
    bit_depth: int = 12
    bytes_per_row: int = 4096
    expected_file_bytes: int = 8_192_000
    interpolation_down: str = "linear"
    interpolation_up: str = "linear"
    row_tail_value: int = 0
    header_bytes: int = 0
    trailer_bytes: int = 0
    sample_packing: str = PACKING_ID
    byte_order: str = BYTE_ORDER_ID
    uint8_to_uint12: str = U8_TO_U12_ID

    @property
    def active_bytes_per_row(self) -> int:
        return ((self.width + 1) // 2) * 3

    @property
    def padding_bytes_per_row(self) -> int:
        return self.bytes_per_row - self.active_bytes_per_row

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise PreprocessError("cam2000 width/height 必须为正整数")
        if self.bit_depth != 12:
            raise PreprocessError("cam2000 仅支持已确认的 12-bit 协议")
        if self.sample_packing != PACKING_ID:
            raise PreprocessError(f"未知 sample_packing: {self.sample_packing!r}")
        if self.byte_order != BYTE_ORDER_ID:
            raise PreprocessError(f"未知 byte_order: {self.byte_order!r}")
        if self.uint8_to_uint12 != U8_TO_U12_ID:
            raise PreprocessError(f"未知 uint8_to_uint12: {self.uint8_to_uint12!r}")
        if self.interpolation_down != "linear" or self.interpolation_up != "linear":
            raise PreprocessError("cam2000 必须使用 OpenCV INTER_LINEAR")
        if self.row_tail_value != 0:
            raise PreprocessError("cam2000 行尾填充值必须为 0")
        if self.header_bytes != 0 or self.trailer_bytes != 0:
            raise PreprocessError("cam2000 协议不包含文件头或文件尾")
        if self.active_bytes_per_row > self.bytes_per_row:
            raise PreprocessError("每行有效数据超过 camera stride")
        calculated = self.header_bytes + self.height * self.bytes_per_row + self.trailer_bytes
        if calculated != self.expected_file_bytes:
            raise PreprocessError(
                f"文件大小不闭合: expected={self.expected_file_bytes}, calculated={calculated}"
            )


def spec_from_profile(profile: Mapping[str, Any]) -> Cam2000Spec:
    """Construct and validate a camera contract from ``cam2000.yaml``."""

    if profile.get("name") != "cam2000":
        raise PreprocessError(f"配置不是 cam2000: {profile.get('name')!r}")
    resize = profile["resize"]
    camera = profile["camera"]
    spec = Cam2000Spec(
        width=int(camera["width"]),
        height=int(camera["height"]),
        bit_depth=int(camera["bit_depth"]),
        bytes_per_row=int(camera["bytes_per_row"]),
        expected_file_bytes=int(camera["expected_file_bytes"]),
        interpolation_down=str(resize["interpolation_down"]),
        interpolation_up=str(resize["interpolation_up"]),
        row_tail_value=int(camera["row_tail_value"]),
        header_bytes=int(camera["header_bytes"]),
        trailer_bytes=int(camera["trailer_bytes"]),
        sample_packing=str(camera["sample_packing"]),
        byte_order=str(camera["byte_order"]),
        uint8_to_uint12=str(camera["uint8_to_uint12"]),
    )
    if int(resize["width"]) != spec.width or int(resize["height"]) != spec.height:
        raise PreprocessError("resize 尺寸必须与 camera 尺寸一致")
    spec.validate()
    return spec


def u8_to_u12(gray_u8: np.ndarray) -> np.ndarray:
    """Map uint8 0..255 to uint12 0..4095 using full-range rounding."""

    if gray_u8.dtype != np.uint8:
        raise PreprocessError(f"8-bit 输入 dtype 必须是 uint8，实际为 {gray_u8.dtype}")
    mapped = np.rint(gray_u8.astype(np.float64) * (4095.0 / 255.0))
    return np.clip(mapped, 0, 4095).astype(np.uint16)


def u12_to_u8(gray_u12: np.ndarray) -> np.ndarray:
    """Map validated uint12 samples back to uint8 for side-view verification."""

    _validate_u12(gray_u12)
    mapped = np.rint(gray_u12.astype(np.float64) * (255.0 / 4095.0))
    return np.clip(mapped, 0, 255).astype(np.uint8)


def _validate_u12(samples: np.ndarray) -> None:
    if not np.issubdtype(samples.dtype, np.integer):
        raise PreprocessError(f"12-bit 输入必须是整数数组，实际为 {samples.dtype}")
    if samples.size and (int(samples.min()) < 0 or int(samples.max()) > 4095):
        raise PreprocessError("12-bit 样本必须位于 0..4095；禁止静默截断")


def pack_12bit_to_bytes(samples: np.ndarray) -> bytes:
    """Pack P0/P1 into ``P0[7:0], P1[3:0]|P0[11:8], P1[11:4]``."""

    values = np.asarray(samples)
    if values.ndim != 1:
        raise PreprocessError(f"打包输入必须是一维数组，实际 shape={values.shape}")
    _validate_u12(values)
    values = values.astype(np.uint16, copy=False)
    if values.size % 2:
        values = np.pad(values, (0, 1), mode="constant", constant_values=0)
    first = values[0::2]
    second = values[1::2]
    packed = np.empty(first.size * 3, dtype=np.uint8)
    packed[0::3] = first & 0xFF
    packed[1::3] = ((second & 0x0F) << 4) | ((first >> 8) & 0x0F)
    packed[2::3] = (second >> 4) & 0xFF
    return packed.tobytes()


def unpack_12bit_from_bytes(payload: bytes | bytearray | memoryview) -> np.ndarray:
    """Decode the exact inverse of :func:`pack_12bit_to_bytes`."""

    packed = np.frombuffer(payload, dtype=np.uint8)
    if packed.size % 3:
        raise PreprocessError("12-bit packed 数据长度必须是 3 的整数倍")
    first = packed[0::3].astype(np.uint16) | (
        (packed[1::3].astype(np.uint16) & 0x0F) << 8
    )
    second = (packed[2::3].astype(np.uint16) << 4) | (
        packed[1::3].astype(np.uint16) >> 4
    )
    output = np.empty(first.size * 2, dtype=np.uint16)
    output[0::2] = first
    output[1::2] = second
    return output


def transform_image_to_u12(
    image: np.ndarray,
    source_semantics: str = "color_to_gray",
    spec: Cam2000Spec = Cam2000Spec(),
) -> np.ndarray:
    """Convert a source PNG image array to the 2000x2000 uint12 sample plane."""

    spec.validate()
    gray = to_gray1(image, source_semantics)
    resized = resize_gray1(
        gray,
        width=spec.width,
        height=spec.height,
        interpolation_down=spec.interpolation_down,
        interpolation_up=spec.interpolation_up,
    )
    return u8_to_u12(resized)


def encode_frame(gray_u12: np.ndarray, spec: Cam2000Spec = Cam2000Spec()) -> bytes:
    """Encode one uint12 frame with fixed row stride and zero-filled row tails."""

    spec.validate()
    samples = np.asarray(gray_u12)
    if samples.shape != (spec.height, spec.width):
        raise PreprocessError(
            f"frame shape 错误: expected={(spec.height, spec.width)}, actual={samples.shape}"
        )
    _validate_u12(samples)
    rows = np.full(
        (spec.height, spec.bytes_per_row), spec.row_tail_value, dtype=np.uint8
    )
    for row_index in range(spec.height):
        active = np.frombuffer(pack_12bit_to_bytes(samples[row_index]), dtype=np.uint8)
        rows[row_index, : spec.active_bytes_per_row] = active
    payload = rows.tobytes()
    if len(payload) != spec.expected_file_bytes:
        raise PreprocessError(
            f"编码文件大小错误: expected={spec.expected_file_bytes}, actual={len(payload)}"
        )
    return payload


def decode_frame(
    payload: bytes | bytearray | memoryview,
    spec: Cam2000Spec = Cam2000Spec(),
    *,
    verify_padding: bool = True,
) -> np.ndarray:
    """Decode one exact-size frame and optionally reject nonzero row padding."""

    spec.validate()
    if len(payload) != spec.expected_file_bytes:
        raise PreprocessError(
            f"bin 文件大小错误: expected={spec.expected_file_bytes}, actual={len(payload)}"
        )
    rows = np.frombuffer(payload, dtype=np.uint8).reshape(spec.height, spec.bytes_per_row)
    if verify_padding and spec.padding_bytes_per_row:
        tails = rows[:, spec.active_bytes_per_row :]
        if np.any(tails != spec.row_tail_value):
            raise PreprocessError("检测到非零或不符合协议的行尾填充字节")
    output = np.empty((spec.height, spec.width), dtype=np.uint16)
    for row_index in range(spec.height):
        unpacked = unpack_12bit_from_bytes(
            rows[row_index, : spec.active_bytes_per_row].tobytes()
        )
        output[row_index] = unpacked[: spec.width]
    return output


def write_camera_bin(
    path: str | Path,
    gray_u12: np.ndarray,
    spec: Cam2000Spec = Cam2000Spec(),
    *,
    overwrite: bool = False,
) -> Path:
    """Encode, verify in memory, and atomically publish one camera bin."""

    payload = encode_frame(gray_u12, spec)
    decoded = decode_frame(payload, spec)
    if not np.array_equal(decoded, gray_u12):
        raise PreprocessError("camera bin 内存回环校验失败")
    return atomic_write_bytes(path, payload, overwrite=overwrite)


def transform_point_to_cam2000(
    x: float,
    y: float,
    *,
    source_width: int,
    source_height: int,
    spec: Cam2000Spec = Cam2000Spec(),
) -> tuple[float, float]:
    """Scale one continuous floating-point source coordinate into camera space."""

    spec.validate()
    if source_width <= 0 or source_height <= 0:
        raise PreprocessError("源图尺寸必须为正整数")
    if not math.isfinite(x) or not math.isfinite(y):
        raise PreprocessError("质心坐标必须是有限浮点数")
    if not 0.0 <= x <= source_width or not 0.0 <= y <= source_height:
        raise PreprocessError("质心坐标超出源图连续坐标范围")
    return x * spec.width / source_width, y * spec.height / source_height


def protocol_summary(spec: Cam2000Spec = Cam2000Spec()) -> dict[str, Any]:
    """Return stable ABI values for manifests, reports, and FPGA review."""

    spec.validate()
    return {
        "pipeline": "cam2000",
        "width": spec.width,
        "height": spec.height,
        "bit_depth": spec.bit_depth,
        "bytes_per_row": spec.bytes_per_row,
        "active_bytes_per_row": spec.active_bytes_per_row,
        "padding_bytes_per_row": spec.padding_bytes_per_row,
        "active_bytes_total": spec.active_bytes_per_row * spec.height,
        "padding_bytes_total": spec.padding_bytes_per_row * spec.height,
        "expected_file_bytes": spec.expected_file_bytes,
        "sample_packing": spec.sample_packing,
        "byte_order": spec.byte_order,
        "uint8_to_uint12": spec.uint8_to_uint12,
        "row_tail_value": spec.row_tail_value,
        "header_bytes": spec.header_bytes,
        "trailer_bytes": spec.trailer_bytes,
        "coordinate_semantics": "continuous_xy_float_no_rounding",
    }
