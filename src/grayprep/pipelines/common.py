"""Shared, deterministic image and file helpers for preprocessing pipelines."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np


SOURCE_SEMANTICS = ("native_gray", "r_only", "color_to_gray")
INTERPOLATIONS = {
    "area": cv2.INTER_AREA,
    "linear": cv2.INTER_LINEAR,
    "nearest": cv2.INTER_NEAREST,
}


class PreprocessError(ValueError):
    """Raised when an input violates an explicit preprocessing contract."""


def read_image(path: str | os.PathLike[str]) -> np.ndarray:
    """Read an image without depending on OpenCV's platform path handling."""

    image_path = Path(path)
    try:
        payload = image_path.read_bytes()
    except OSError as exc:
        raise PreprocessError(f"无法读取图片: {image_path}: {exc}") from exc
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise PreprocessError(f"无法解码图片: {image_path}")
    return image


def _require_uint8(image: np.ndarray) -> None:
    if image.dtype != np.uint8:
        raise PreprocessError(f"输入 dtype 必须是 uint8，实际为 {image.dtype}")


def to_gray1(image: np.ndarray, semantics: str) -> np.ndarray:
    """Convert an image to one uint8 plane using explicit source semantics."""

    if semantics not in SOURCE_SEMANTICS:
        raise PreprocessError(
            f"未知输入语义 {semantics!r}，可选值为 {', '.join(SOURCE_SEMANTICS)}"
        )
    _require_uint8(image)

    if semantics == "native_gray":
        if image.ndim == 2:
            gray = image
        elif image.ndim == 3 and image.shape[2] == 1:
            gray = image[:, :, 0]
        else:
            raise PreprocessError(
                f"native_gray 只接受二维或单通道图片，实际 shape={image.shape}"
            )
    elif semantics == "r_only":
        if image.ndim != 3 or image.shape[2] < 3:
            raise PreprocessError(
                f"r_only 要求至少三通道 BGR 图片，实际 shape={image.shape}"
            )
        gray = image[:, :, 2]
    else:
        if image.ndim != 3 or image.shape[2] < 3:
            raise PreprocessError(
                f"color_to_gray 要求至少三通道 BGR 图片，实际 shape={image.shape}"
            )
        gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)

    return np.ascontiguousarray(gray, dtype=np.uint8)


def load_gray1(path: str | os.PathLike[str], semantics: str) -> np.ndarray:
    """Read an image and resolve it to one uint8 grayscale plane."""

    return to_gray1(read_image(path), semantics)


def resize_gray1(
    gray: np.ndarray,
    *,
    width: int,
    height: int,
    interpolation_down: str = "area",
    interpolation_up: str = "linear",
) -> np.ndarray:
    """Resize one grayscale plane with a deterministic up/down policy."""

    _require_uint8(gray)
    if gray.ndim != 2:
        raise PreprocessError(f"resize_gray1 只接受二维图片，实际 shape={gray.shape}")
    if width <= 0 or height <= 0:
        raise PreprocessError(f"目标尺寸必须为正整数，实际 width={width}, height={height}")
    if interpolation_down not in INTERPOLATIONS:
        raise PreprocessError(f"未知缩小插值方式: {interpolation_down}")
    if interpolation_up not in INTERPOLATIONS:
        raise PreprocessError(f"未知放大插值方式: {interpolation_up}")

    source_height, source_width = gray.shape
    shrinking = width * height <= source_width * source_height
    interpolation_name = interpolation_down if shrinking else interpolation_up
    resized = cv2.resize(
        gray,
        (width, height),
        interpolation=INTERPOLATIONS[interpolation_name],
    )
    if resized.shape != (height, width):
        raise PreprocessError(
            f"resize 输出尺寸错误: expected={(height, width)}, actual={resized.shape}"
        )
    return np.ascontiguousarray(resized, dtype=np.uint8)


def encode_gray_png(gray: np.ndarray, *, compression: int = 3) -> bytes:
    """Encode a two-dimensional uint8 image as PNG bytes."""

    _require_uint8(gray)
    if gray.ndim != 2:
        raise PreprocessError(f"PNG 输出必须是二维灰度图，实际 shape={gray.shape}")
    if not 0 <= compression <= 9:
        raise PreprocessError("PNG compression 必须位于 0..9")
    ok, encoded = cv2.imencode(
        ".png", gray, [cv2.IMWRITE_PNG_COMPRESSION, int(compression)]
    )
    if not ok:
        raise PreprocessError("OpenCV PNG 编码失败")
    return encoded.tobytes()


def atomic_write_bytes(
    path: str | os.PathLike[str], payload: bytes, *, overwrite: bool = False
) -> Path:
    """Write a sibling `.partial`, fsync it, then atomically publish it."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"输出已存在且禁止覆盖: {destination}")
    if partial.exists():
        raise FileExistsError(f"检测到未处理的临时文件: {partial}")

    created = False
    try:
        with partial.open("xb") as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, destination)
    except Exception:
        if created:
            partial.unlink(missing_ok=True)
        raise
    return destination


def write_gray_png(
    path: str | os.PathLike[str],
    gray: np.ndarray,
    *,
    compression: int = 3,
    overwrite: bool = False,
) -> Path:
    """Encode and atomically publish a one-channel PNG."""

    return atomic_write_bytes(
        path, encode_gray_png(gray, compression=compression), overwrite=overwrite
    )


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Return the SHA-256 digest of a file using bounded memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    """Hash structured metadata with stable JSON serialization."""

    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def image_metadata(gray: np.ndarray) -> dict[str, Any]:
    """Return stable metadata for a gray1 plane."""

    _require_uint8(gray)
    if gray.ndim != 2:
        raise PreprocessError(f"元数据输入必须是二维灰度图，实际 shape={gray.shape}")
    height, width = gray.shape
    return {
        "width": width,
        "height": height,
        "channels": 1,
        "dtype": "uint8",
        "min": int(gray.min()),
        "max": int(gray.max()),
    }
