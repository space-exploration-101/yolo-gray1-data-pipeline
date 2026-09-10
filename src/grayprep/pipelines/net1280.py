"""Deterministic 1000x1000 + 140-pixel padding pipeline for YOLO-Pose."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from grayprep.pipelines.common import PreprocessError, resize_gray1, to_gray1


@dataclass(frozen=True)
class Net1280Spec:
    """Frozen geometry contract for the net1280 pipeline."""

    resize_width: int = 1000
    resize_height: int = 1000
    pad_left: int = 140
    pad_right: int = 140
    pad_top: int = 140
    pad_bottom: int = 140
    pad_value: int = 0
    output_width: int = 1280
    output_height: int = 1280
    interpolation_down: str = "area"
    interpolation_up: str = "linear"

    def validate(self) -> None:
        if self.resize_width + self.pad_left + self.pad_right != self.output_width:
            raise PreprocessError("net1280 水平方向尺寸不闭合")
        if self.resize_height + self.pad_top + self.pad_bottom != self.output_height:
            raise PreprocessError("net1280 垂直方向尺寸不闭合")
        if not 0 <= self.pad_value <= 255:
            raise PreprocessError("padding 值必须位于 uint8 范围")


@dataclass(frozen=True)
class PoseKeypoint:
    x: float
    y: float
    visibility: float


@dataclass(frozen=True)
class YoloPoseLabel:
    class_id: int
    center_x: float
    center_y: float
    width: float
    height: float
    keypoints: tuple[PoseKeypoint, ...]


def spec_from_profile(profile: Mapping[str, Any]) -> Net1280Spec:
    """Construct the geometry contract from a validated net1280 profile."""

    if profile.get("name") != "net1280":
        raise PreprocessError(f"配置不是 net1280: {profile.get('name')!r}")
    resize = profile["resize"]
    padding = profile["padding"]
    output = profile["output"]
    spec = Net1280Spec(
        resize_width=int(resize["width"]),
        resize_height=int(resize["height"]),
        pad_left=int(padding["left"]),
        pad_right=int(padding["right"]),
        pad_top=int(padding["top"]),
        pad_bottom=int(padding["bottom"]),
        pad_value=int(padding["value"]),
        output_width=int(output["width"]),
        output_height=int(output["height"]),
        interpolation_down=str(resize["interpolation_down"]),
        interpolation_up=str(resize["interpolation_up"]),
    )
    spec.validate()
    return spec


def transform_image(
    image: np.ndarray, source_semantics: str, spec: Net1280Spec = Net1280Spec()
) -> np.ndarray:
    """Produce one 1280x1280 uint8 gray1 image from an in-memory source."""

    spec.validate()
    gray = to_gray1(image, source_semantics)
    resized = resize_gray1(
        gray,
        width=spec.resize_width,
        height=spec.resize_height,
        interpolation_down=spec.interpolation_down,
        interpolation_up=spec.interpolation_up,
    )
    output = cv2.copyMakeBorder(
        resized,
        spec.pad_top,
        spec.pad_bottom,
        spec.pad_left,
        spec.pad_right,
        cv2.BORDER_CONSTANT,
        value=spec.pad_value,
    )
    if output.shape != (spec.output_height, spec.output_width):
        raise PreprocessError(
            f"net1280 输出尺寸错误: expected={(spec.output_height, spec.output_width)}, "
            f"actual={output.shape}"
        )
    return np.ascontiguousarray(output, dtype=np.uint8)


def _finite(value: float, field: str) -> float:
    if not math.isfinite(value):
        raise PreprocessError(f"{field} 必须是有限数值")
    return value


def _normalized(value: float, field: str) -> float:
    _finite(value, field)
    if not 0.0 <= value <= 1.0:
        raise PreprocessError(f"{field} 必须位于 0..1，实际为 {value}")
    return value


def parse_label_line(line: str, *, keypoint_count: int = 2) -> YoloPoseLabel:
    """Parse one `class + xywh + keypoint(x,y,v)*K` YOLO-Pose row."""

    tokens = line.split()
    expected = 5 + keypoint_count * 3
    if len(tokens) != expected:
        raise PreprocessError(f"标签列数错误: expected={expected}, actual={len(tokens)}")
    try:
        class_value = float(tokens[0])
        values = [float(value) for value in tokens[1:]]
    except ValueError as exc:
        raise PreprocessError(f"标签包含非数值字段: {line!r}") from exc
    if not class_value.is_integer() or class_value < 0:
        raise PreprocessError(f"class_id 必须是非负整数，实际为 {tokens[0]!r}")

    center_x = _normalized(values[0], "bbox.center_x")
    center_y = _normalized(values[1], "bbox.center_y")
    width = _normalized(values[2], "bbox.width")
    height = _normalized(values[3], "bbox.height")
    if width <= 0 or height <= 0:
        raise PreprocessError("bbox width/height 必须大于 0")

    keypoints = []
    for index in range(keypoint_count):
        offset = 4 + index * 3
        x, y, visibility = values[offset : offset + 3]
        _finite(visibility, f"keypoint[{index}].visibility")
        if visibility < 0:
            raise PreprocessError(f"keypoint[{index}] visibility 不能小于 0")
        if not (visibility == 0 and x == 0 and y == 0):
            _normalized(x, f"keypoint[{index}].x")
            _normalized(y, f"keypoint[{index}].y")
        keypoints.append(PoseKeypoint(x, y, visibility))

    return YoloPoseLabel(
        int(class_value), center_x, center_y, width, height, tuple(keypoints)
    )


def _transform_xy(
    x: float,
    y: float,
    *,
    source_width: int,
    source_height: int,
    spec: Net1280Spec,
) -> tuple[float, float]:
    pixel_x = x * source_width
    pixel_y = y * source_height
    output_x = pixel_x * spec.resize_width / source_width + spec.pad_left
    output_y = pixel_y * spec.resize_height / source_height + spec.pad_top
    return output_x / spec.output_width, output_y / spec.output_height


def transform_label(
    label: YoloPoseLabel,
    *,
    source_width: int,
    source_height: int,
    spec: Net1280Spec = Net1280Spec(),
) -> YoloPoseLabel:
    """Transform one normalized source label into the padded output coordinates."""

    spec.validate()
    if source_width <= 0 or source_height <= 0:
        raise PreprocessError("源图尺寸必须为正整数")

    center_x, center_y = _transform_xy(
        label.center_x,
        label.center_y,
        source_width=source_width,
        source_height=source_height,
        spec=spec,
    )
    width = label.width * spec.resize_width / spec.output_width
    height = label.height * spec.resize_height / spec.output_height

    keypoints = []
    for keypoint in label.keypoints:
        if keypoint.visibility == 0 and keypoint.x == 0 and keypoint.y == 0:
            keypoints.append(keypoint)
            continue
        x, y = _transform_xy(
            keypoint.x,
            keypoint.y,
            source_width=source_width,
            source_height=source_height,
            spec=spec,
        )
        keypoints.append(PoseKeypoint(x, y, keypoint.visibility))

    transformed = YoloPoseLabel(
        label.class_id, center_x, center_y, width, height, tuple(keypoints)
    )
    for field, value in (
        ("bbox.center_x", transformed.center_x),
        ("bbox.center_y", transformed.center_y),
        ("bbox.width", transformed.width),
        ("bbox.height", transformed.height),
    ):
        _normalized(value, field)
    return transformed


def _format_float(value: float) -> str:
    return f"{value:.8f}"


def format_label(label: YoloPoseLabel) -> str:
    """Serialize one label deterministically with eight decimal places."""

    tokens = [
        str(label.class_id),
        _format_float(label.center_x),
        _format_float(label.center_y),
        _format_float(label.width),
        _format_float(label.height),
    ]
    for keypoint in label.keypoints:
        tokens.extend(
            [
                _format_float(keypoint.x),
                _format_float(keypoint.y),
                f"{keypoint.visibility:g}",
            ]
        )
    return " ".join(tokens)


def transform_label_text(
    text: str,
    *,
    source_width: int,
    source_height: int,
    keypoint_count: int = 2,
    spec: Net1280Spec = Net1280Spec(),
) -> str:
    """Transform a complete YOLO-Pose label file with deterministic output."""

    output_lines = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = parse_label_line(line, keypoint_count=keypoint_count)
            transformed = transform_label(
                parsed,
                source_width=source_width,
                source_height=source_height,
                spec=spec,
            )
        except PreprocessError as exc:
            raise PreprocessError(f"标签第 {line_number} 行错误: {exc}") from exc
        output_lines.append(format_label(transformed))
    return "\n".join(output_lines) + ("\n" if output_lines else "")


def transform_summary(
    *, source_width: int, source_height: int, spec: Net1280Spec = Net1280Spec()
) -> dict[str, Any]:
    """Return the geometry values required by manifests and reviews."""

    spec.validate()
    if source_width <= 0 or source_height <= 0:
        raise PreprocessError("源图尺寸必须为正整数")
    return {
        "pipeline": "net1280",
        "source_width": source_width,
        "source_height": source_height,
        "resize_width": spec.resize_width,
        "resize_height": spec.resize_height,
        "scale_x": spec.resize_width / source_width,
        "scale_y": spec.resize_height / source_height,
        "padding": {
            "left": spec.pad_left,
            "right": spec.pad_right,
            "top": spec.pad_top,
            "bottom": spec.pad_bottom,
            "value": spec.pad_value,
        },
        "output_width": spec.output_width,
        "output_height": spec.output_height,
        "output_channels": 1,
        "output_dtype": "uint8",
    }
