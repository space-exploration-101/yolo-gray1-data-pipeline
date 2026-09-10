"""Deterministic bounded dataset selection, materialization, and verification."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import cv2
from jsonschema import Draft202012Validator
import numpy as np
import yaml

from grayprep.pipelines.cam2000 import (
    decode_frame,
    encode_frame,
    spec_from_profile as cam_spec_from_profile,
    transform_image_to_u12,
    write_camera_bin,
)
from grayprep.pipelines.common import (
    PreprocessError,
    atomic_write_bytes,
    canonical_json_sha256,
    read_image,
    sha256_file,
    write_gray_png,
)
from grayprep.pipelines.net1280 import (
    parse_label_line,
    spec_from_profile as net_spec_from_profile,
    transform_image,
    transform_label_text,
)


SPLITS = ("train", "val", "test", "calibration")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreprocessError(f"YAML 顶层必须是对象: {path}")
    return value


def _class_names(dataset: Mapping[str, Any]) -> list[str]:
    names = dataset.get("names")
    if isinstance(names, list) and all(isinstance(name, str) for name in names):
        return names
    if isinstance(names, dict):
        try:
            return [str(names[index]) for index in range(len(names))]
        except KeyError as exc:
            raise PreprocessError("dataset names 字典必须使用连续整数键") from exc
    raise PreprocessError("dataset.yaml 缺少有效 names")


def _candidate_key(seed: int, split: str, relative_label: str) -> str:
    return hashlib.sha256(f"{seed}|{split}|{relative_label}".encode()).hexdigest()


def _index_images(root: Path, split: str) -> dict[str, Path]:
    """Index a split once; avoid a full directory glob for every label."""

    indexed: dict[str, Path] = {}
    for path in sorted((root / "images" / split).iterdir()):
        if not path.is_file():
            continue
        if path.stem in indexed:
            raise PreprocessError(f"图片 stem 重复: {split}/{path.stem}")
        indexed[path.stem] = path
    return indexed


def create_smoke_manifest(
    source_root: str | os.PathLike[str], *, seed: int, per_class: int = 1
) -> dict[str, Any]:
    """Select disjoint train/val/test/calibration samples deterministically."""

    root = Path(source_root)
    dataset_path = root / "dataset.yaml"
    dataset = _load_yaml(dataset_path)
    names = _class_names(dataset)
    if per_class <= 0:
        raise PreprocessError("per_class 必须大于 0")
    if dataset.get("r_channel_only") is not True:
        raise PreprocessError("烟测选择要求 dataset.yaml 明确 r_channel_only: true")

    candidates: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for split in ("train", "val", "test"):
        images_by_stem = _index_images(root, split)
        by_class: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for label_path in sorted((root / "labels" / split).glob("*.txt")):
            rows = [line.strip() for line in label_path.read_text().splitlines() if line.strip()]
            if not rows:
                continue
            parsed = [parse_label_line(row, keypoint_count=2) for row in rows]
            classes = {label.class_id for label in parsed}
            if len(classes) != 1:
                continue
            class_id = next(iter(classes))
            if not 0 <= class_id < len(names):
                raise PreprocessError(f"class_id 超出 names: {class_id}")
            image_path = images_by_stem.get(label_path.stem)
            if image_path is None:
                raise PreprocessError(f"标签缺少匹配图片: {split}/{label_path.stem}")
            relative_label = label_path.relative_to(root).as_posix()
            by_class[class_id].append(
                {
                    "class_id": class_id,
                    "source_split": split,
                    "source_image": image_path.relative_to(root).as_posix(),
                    "source_label": relative_label,
                    "rank": _candidate_key(seed, split, relative_label),
                }
            )
        for values in by_class.values():
            values.sort(key=lambda item: (item["rank"], item["source_label"]))
        candidates[split] = by_class

    items: list[dict[str, Any]] = []
    for class_id, class_name in enumerate(names):
        if len(candidates["train"].get(class_id, [])) < per_class * 2:
            raise PreprocessError(f"类别 {class_name} 的 train 样本不足 {per_class * 2}")
        for output_split, source_split, offset in (
            ("train", "train", 0),
            ("calibration", "train", per_class),
            ("val", "val", 0),
            ("test", "test", 0),
        ):
            available = candidates[source_split].get(class_id, [])
            if len(available) < offset + per_class:
                raise PreprocessError(f"类别 {class_name} 的 {source_split} 样本不足")
            for selected in available[offset : offset + per_class]:
                item = {key: value for key, value in selected.items() if key != "rank"}
                item.update({"split": output_split, "class_name": class_name})
                items.append(item)

    items.sort(key=lambda item: (SPLITS.index(item["split"]), item["class_id"], item["source_image"]))
    relative_sources = [item["source_image"] for item in items]
    if len(relative_sources) != len(set(relative_sources)):
        raise PreprocessError("烟测选择出现重复源图片")
    return {
        "schema_version": 1,
        "manifest_type": "grayprep-smoke-selection",
        "dataset_id": "yolo_full",
        "source_dataset_yaml": "dataset.yaml",
        "source_dataset_yaml_sha256": sha256_file(dataset_path),
        "source_semantics": "r_only",
        "seed": seed,
        "per_class_per_split": per_class,
        "class_names": names,
        "item_count": len(items),
        "items": items,
    }


def write_selection_manifest(path: str | os.PathLike[str], manifest: Mapping[str, Any]) -> Path:
    return atomic_write_bytes(path, _json_bytes(manifest))


def _require_r_only(image: np.ndarray, relative_path: str) -> None:
    if image.ndim != 3 or image.shape[2] < 3:
        raise PreprocessError(f"R-only 源图必须至少三通道: {relative_path}, {image.shape}")
    if np.any(image[:, :, 0]) or np.any(image[:, :, 1]):
        raise PreprocessError(f"R-only 源图的 B/G 通道不为零: {relative_path}")


def _write_sha256sums(root: Path) -> str:
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.name not in {"SHA256SUMS", "VERIFIED"})
    lines = [f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in files]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    atomic_write_bytes(root / "SHA256SUMS", payload)
    return hashlib.sha256(payload).hexdigest()


def build_smoke_dataset(
    source_root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    net_profile_path: str | os.PathLike[str],
    cam_profile_path: str | os.PathLike[str],
    schema_path: str | os.PathLike[str],
) -> Path:
    """Materialize a bounded smoke dataset through a verified staging directory."""

    root = Path(source_root)
    destination = Path(output)
    staging = destination.with_name(destination.name + ".partial")
    if destination.exists() or staging.exists():
        raise FileExistsError(f"输出或暂存目录已存在: {destination}")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("manifest_type") != "grayprep-smoke-selection":
        raise PreprocessError("输入不是 smoke selection manifest")
    if manifest.get("source_semantics") != "r_only":
        raise PreprocessError("当前 yolo_full 烟测必须显式使用 r_only")
    if sha256_file(root / "dataset.yaml") != manifest["source_dataset_yaml_sha256"]:
        raise PreprocessError("源 dataset.yaml 与选择 manifest 不一致")

    net_profile = _load_yaml(Path(net_profile_path))
    cam_profile = _load_yaml(Path(cam_profile_path))
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(net_profile)
    Draft202012Validator(schema).validate(cam_profile)
    net_spec = net_spec_from_profile(net_profile)
    cam_spec = cam_spec_from_profile(cam_profile)

    staging.mkdir(parents=True)
    output_items = []
    statistics = {split: Counter() for split in SPLITS}
    atomic_write_bytes(staging / "selection_manifest.json", _json_bytes(manifest))
    resolved = {
        "net1280": net_profile,
        "net1280_sha256": canonical_json_sha256(net_profile),
        "cam2000": cam_profile,
        "cam2000_sha256": canonical_json_sha256(cam_profile),
    }
    atomic_write_bytes(
        staging / "profiles.resolved.yaml",
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True).encode("utf-8"),
    )

    for item in manifest["items"]:
        split = item["split"]
        source_image = root / item["source_image"]
        source_label = root / item["source_label"]
        image = read_image(source_image)
        _require_r_only(image, item["source_image"])
        source_height, source_width = image.shape[:2]
        label_text = source_label.read_text(encoding="utf-8")

        net_image = transform_image(image, "r_only", net_spec)
        net_label = transform_label_text(
            label_text,
            source_width=source_width,
            source_height=source_height,
            keypoint_count=2,
            spec=net_spec,
        )
        stem = source_image.stem
        output_image_rel = f"images/{split}/{stem}.png"
        output_label_rel = f"labels/{split}/{stem}.txt"
        write_gray_png(staging / output_image_rel, net_image)
        atomic_write_bytes(staging / output_label_rel, net_label.encode("utf-8"))

        output_item = {
            **item,
            "source_width": source_width,
            "source_height": source_height,
            "source_image_sha256": sha256_file(source_image),
            "source_label_sha256": sha256_file(source_label),
            "output_image": output_image_rel,
            "output_label": output_label_rel,
            "output_image_sha256": sha256_file(staging / output_image_rel),
            "output_label_sha256": sha256_file(staging / output_label_rel),
            "resize_scale_x": net_spec.resize_width / source_width,
            "resize_scale_y": net_spec.resize_height / source_height,
            "padding": [net_spec.pad_left, net_spec.pad_top, net_spec.pad_right, net_spec.pad_bottom],
        }
        if split == "test":
            fpga_rel = f"fpga/test/{stem}.bin"
            u12 = transform_image_to_u12(image, "r_only", cam_spec)
            write_camera_bin(staging / fpga_rel, u12, cam_spec)
            output_item.update(
                {
                    "fpga_bin": fpga_rel,
                    "fpga_bin_bytes": (staging / fpga_rel).stat().st_size,
                    "fpga_bin_sha256": sha256_file(staging / fpga_rel),
                }
            )
        output_items.append(output_item)
        statistics[split][str(item["class_id"])] += 1

    output_manifest = {
        "schema_version": 1,
        "manifest_type": "grayprep-smoke-output",
        "dataset_id": manifest["dataset_id"],
        "source_semantics": "r_only",
        "class_names": manifest["class_names"],
        "profile_hashes": {"net1280": resolved["net1280_sha256"], "cam2000": resolved["cam2000_sha256"]},
        "item_count": len(output_items),
        "items": output_items,
    }
    atomic_write_bytes(staging / "manifest.json", _json_bytes(output_manifest))
    atomic_write_bytes(
        staging / "class_statistics.json",
        _json_bytes({split: dict(sorted(counts.items())) for split, counts in statistics.items()}),
    )
    dataset_yaml = {
        "path": ".",
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "calibration": "images/calibration",
        "kpt_shape": [2, 3],
        "flip_idx": [0, 1],
        "channels": 1,
        "input_semantics": "gray1",
        "names": manifest["class_names"],
    }
    atomic_write_bytes(
        staging / "dataset.yaml",
        yaml.safe_dump(dataset_yaml, sort_keys=False, allow_unicode=True).encode("utf-8"),
    )
    report = {
        "status": "built_pending_step10_verification",
        "items": len(output_items),
        "net_images": len(output_items),
        "labels": len(output_items),
        "fpga_bins": sum("fpga_bin" in item for item in output_items),
        "class_count": len(manifest["class_names"]),
        "splits": list(SPLITS),
    }
    atomic_write_bytes(staging / "transform_report.json", _json_bytes(report))
    sha256sums_sha256 = _write_sha256sums(staging)
    os.replace(staging, destination)
    atomic_write_bytes(
        destination / "VERIFIED",
        _json_bytes({"stage": 9, "status": "BUILT", "sha256sums_sha256": sha256sums_sha256}),
    )
    return destination


def verify_smoke_dataset(
    output: str | os.PathLike[str], *, source_root: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    """Verify hashes, split isolation, net images/labels, and FPGA bins."""

    root = Path(output)
    if not root.is_dir() or not (root / "VERIFIED").is_file():
        raise PreprocessError("输出目录不存在或缺少 VERIFIED")
    failures = []
    checked_hashes = 0
    for line in (root / "SHA256SUMS").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        actual = sha256_file(path) if path.is_file() else "MISSING"
        if actual != expected:
            failures.append(f"hash:{relative}")
        checked_hashes += 1

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    names = manifest["class_names"]
    split_counts = {split: Counter() for split in SPLITS}
    stems_by_split = {split: set() for split in SPLITS}
    source_hashes_by_split = {split: set() for split in SPLITS}
    bins_checked = 0
    for item in manifest["items"]:
        split = item["split"]
        split_counts[split][item["class_id"]] += 1
        stem = Path(item["source_image"]).stem
        stems_by_split[split].add(stem)
        source_hashes_by_split[split].add(item["source_image_sha256"])
        image = cv2.imread(str(root / item["output_image"]), cv2.IMREAD_UNCHANGED)
        if image is None or image.shape != (1280, 1280) or image.dtype != np.uint8:
            failures.append(f"image:{item['output_image']}")
        label_text = (root / item["output_label"]).read_text(encoding="utf-8")
        for row in label_text.splitlines():
            if row.strip():
                parse_label_line(row, keypoint_count=2)
        if split == "test":
            payload = (root / item["fpga_bin"]).read_bytes()
            decoded = decode_frame(payload)
            if encode_frame(decoded) != payload:
                failures.append(f"bin_roundtrip:{item['fpga_bin']}")
            bins_checked += 1
        if source_root is not None:
            source = Path(source_root) / item["source_image"]
            if sha256_file(source) != item["source_image_sha256"]:
                failures.append(f"source_hash:{item['source_image']}")
            _require_r_only(read_image(source), item["source_image"])

    expected_classes = set(range(len(names)))
    for split in SPLITS:
        if set(split_counts[split]) != expected_classes:
            failures.append(f"class_coverage:{split}")
    for index, left in enumerate(SPLITS):
        for right in SPLITS[index + 1 :]:
            if stems_by_split[left] & stems_by_split[right]:
                failures.append(f"stem_overlap:{left}:{right}")
            if source_hashes_by_split[left] & source_hashes_by_split[right]:
                failures.append(f"content_overlap:{left}:{right}")
    report = {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "items_checked": len(manifest["items"]),
        "hashes_checked": checked_hashes,
        "bins_checked": bins_checked,
        "class_count": len(names),
        "split_counts": {split: {str(key): value for key, value in sorted(counts.items())} for split, counts in split_counts.items()},
    }
    if failures:
        raise PreprocessError(f"smoke 验证失败: {failures}")
    return report
