"""Production indexing, resumable materialization, and verification for full datasets."""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

import cv2
from jsonschema import Draft202012Validator
import numpy as np
import yaml

from grayprep.dataset_smoke import (
    _class_names,
    _index_images,
    _json_bytes,
    _load_yaml,
    _require_r_only,
    _validate_parallel_settings,
    _write_sha256sums,
)
from grayprep.pipelines.common import (
    PreprocessError,
    atomic_write_bytes,
    canonical_json_sha256,
    sha256_file,
    write_gray_png,
)
from grayprep.pipelines.net1280 import (
    parse_label_line,
    spec_from_profile,
    transform_image,
    transform_label_text,
)


FULL_SPLITS = ("train", "val", "test")
_GROUP_SUFFIX = re.compile(r"_view_\d+$")
_FULL_WORKER_STATE: dict[str, Any] = {}
_VERIFY_WORKER_STATE: dict[str, Any] = {}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreprocessError(f"JSON 顶层必须是对象: {path}")
    return value


def _validate_schema(value: Mapping[str, Any], schema_path: str | os.PathLike[str]) -> None:
    schema = _load_json(Path(schema_path))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def _group_id(stem: str) -> str:
    return _GROUP_SUFFIX.sub("", stem)


def _source_revision(items: list[Mapping[str, Any]], dataset_yaml_sha256: str) -> str:
    evidence = {
        "dataset_yaml_sha256": dataset_yaml_sha256,
        "items": [
            {
                "source_image": item["source_image"],
                "source_image_size": item["source_image_size"],
                "source_image_mtime_ns": item["source_image_mtime_ns"],
                "source_label": item["source_label"],
                "source_label_sha256": item["source_label_sha256"],
            }
            for item in items
        ],
    }
    return canonical_json_sha256(evidence)


def create_full_manifest(
    source_root: str | os.PathLike[str],
    *,
    schema_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Index every image/label pair without decoding the image payload."""

    root = Path(source_root)
    dataset_path = root / "dataset.yaml"
    dataset = _load_yaml(dataset_path)
    names = _class_names(dataset)
    if dataset.get("r_channel_only") is not True:
        raise PreprocessError("全量索引要求 dataset.yaml 明确 r_channel_only: true")
    if dataset.get("kpt_shape") != [2, 3]:
        raise PreprocessError("全量索引要求 kpt_shape: [2, 3]")

    items: list[dict[str, Any]] = []
    groups_by_split: dict[str, set[str]] = {}
    counts: dict[str, dict[str, Any]] = {}
    for split in FULL_SPLITS:
        images = _index_images(root, split)
        labels = {path.stem: path for path in sorted((root / "labels" / split).glob("*.txt"))}
        missing_labels = sorted(set(images) - set(labels))
        orphan_labels = sorted(set(labels) - set(images))
        if missing_labels:
            raise PreprocessError(f"{split} 图片缺少标签: {missing_labels[:5]}")
        if orphan_labels:
            raise PreprocessError(f"{split} 标签缺少图片: {orphan_labels[:5]}")

        groups: set[str] = set()
        empty_labels = 0
        rows_per_class: Counter[int] = Counter()
        for stem in sorted(images):
            image_path = images[stem]
            label_path = labels[stem]
            label_payload = label_path.read_bytes()
            try:
                label_text = label_payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PreprocessError(f"标签不是 UTF-8: {label_path}") from exc
            rows = [line.strip() for line in label_text.splitlines() if line.strip()]
            class_ids: list[int] = []
            for row in rows:
                parsed = parse_label_line(row, keypoint_count=2)
                if parsed.class_id >= len(names):
                    raise PreprocessError(f"class_id 超出 names: {split}/{label_path.name}")
                class_ids.append(parsed.class_id)
                rows_per_class[parsed.class_id] += 1
            if not rows:
                empty_labels += 1
            group_id = _group_id(stem)
            groups.add(group_id)
            image_stat = image_path.stat()
            label_stat = label_path.stat()
            items.append(
                {
                    "split": split,
                    "group_id": group_id,
                    "source_image": image_path.relative_to(root).as_posix(),
                    "source_label": label_path.relative_to(root).as_posix(),
                    "source_image_size": image_stat.st_size,
                    "source_image_mtime_ns": image_stat.st_mtime_ns,
                    "source_label_size": label_stat.st_size,
                    "source_label_mtime_ns": label_stat.st_mtime_ns,
                    "source_label_sha256": hashlib.sha256(label_payload).hexdigest(),
                    "is_empty": not rows,
                    "row_count": len(rows),
                    "class_ids": class_ids,
                }
            )
        groups_by_split[split] = groups
        counts[split] = {
            "images": len(images),
            "labels": len(labels),
            "empty_labels": empty_labels,
            "groups": len(groups),
            "rows_per_class": {str(key): value for key, value in sorted(rows_per_class.items())},
        }

    for index, left in enumerate(FULL_SPLITS):
        for right in FULL_SPLITS[index + 1 :]:
            overlap = groups_by_split[left] & groups_by_split[right]
            if overlap:
                raise PreprocessError(f"group 跨 split: {left}/{right}: {sorted(overlap)[:5]}")

    dataset_yaml_sha256 = sha256_file(dataset_path)
    manifest = {
        "schema_version": 1,
        "manifest_type": "grayprep-full-index",
        "dataset_id": root.name,
        "source_dataset_yaml": "dataset.yaml",
        "source_dataset_yaml_sha256": dataset_yaml_sha256,
        "source_semantics": "r_only",
        "class_names": names,
        "kpt_shape": [2, 3],
        "split_counts": counts,
        "item_count": len(items),
        "source_revision": _source_revision(items, dataset_yaml_sha256),
        "items": items,
    }
    _validate_schema(manifest, schema_path)
    return manifest


def write_full_manifest(path: str | os.PathLike[str], manifest: Mapping[str, Any]) -> Path:
    return atomic_write_bytes(path, _json_bytes(manifest))


def _selection_key(seed: str, item: Mapping[str, Any]) -> str:
    return hashlib.sha256(f"{seed}|{item['source_image']}".encode()).hexdigest()


def _split_counts(items: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for split in FULL_SPLITS:
        split_items = [item for item in items if item["split"] == split]
        rows_per_class: Counter[int] = Counter()
        for item in split_items:
            rows_per_class.update(item["class_ids"])
        counts[split] = {
            "images": len(split_items),
            "labels": len(split_items),
            "empty_labels": sum(bool(item["is_empty"]) for item in split_items),
            "groups": len({item["group_id"] for item in split_items}),
            "rows_per_class": {str(key): value for key, value in sorted(rows_per_class.items())},
        }
    return counts


def create_medium_manifest(
    parent_manifest_path: str | os.PathLike[str],
    *,
    schema_path: str | os.PathLike[str],
    seed: str,
    views_per_group: int = 10,
    empty_per_group: int = 2,
    moon_train: int = 600,
) -> dict[str, Any]:
    """Select the fixed M-scale training set while retaining complete val/test splits."""

    if not seed:
        raise PreprocessError("seed 不能为空")
    if views_per_group <= 0:
        raise PreprocessError("views_per_group 必须大于 0")
    if empty_per_group < 0 or empty_per_group > views_per_group:
        raise PreprocessError("empty_per_group 必须位于 0..views_per_group")
    if moon_train <= 0:
        raise PreprocessError("moon_train 必须大于 0")

    parent_path = Path(parent_manifest_path)
    parent = _load_json(parent_path)
    _validate_schema(parent, schema_path)
    if parent.get("manifest_type") != "grayprep-full-index":
        raise PreprocessError("M 规模选择要求未经筛选的 full index manifest")
    names = parent["class_names"]
    if len(names) != 21 or names[-1] != "moon":
        raise PreprocessError("M 规模选择要求固定的 20 个地标加 moon 类别表")

    train_items = [item for item in parent["items"] if item["split"] == "train"]
    moon_items = [item for item in train_items if item["class_ids"] == [20]]
    if len(moon_items) < moon_train:
        raise PreprocessError(f"moon 训练样本不足 {moon_train}")
    selected_train = sorted(moon_items, key=lambda item: _selection_key(seed, item))[:moon_train]

    earth_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in train_items:
        if item["class_ids"] == [20]:
            continue
        earth_groups[str(item["group_id"])].append(item)
    if not earth_groups:
        raise PreprocessError("没有可选择的地标 group")
    for group_id, group_items in sorted(earth_groups.items()):
        classes = {class_id for item in group_items for class_id in item["class_ids"]}
        if len(classes) != 1 or not classes.issubset(set(range(20))):
            raise PreprocessError(f"地标 group 类别不唯一: {group_id}: {sorted(classes)}")
        empty = sorted(
            (item for item in group_items if item["is_empty"]),
            key=lambda item: _selection_key(seed, item),
        )
        positive = sorted(
            (item for item in group_items if not item["is_empty"]),
            key=lambda item: _selection_key(seed, item),
        )
        chosen_empty = empty[:empty_per_group]
        chosen = list(chosen_empty)
        chosen.extend(positive[: views_per_group - len(chosen)])
        if len(chosen) < views_per_group:
            remaining = views_per_group - len(chosen)
            chosen.extend(empty[len(chosen_empty) : len(chosen_empty) + remaining])
        if len(chosen) != views_per_group:
            raise PreprocessError(
                f"group {group_id} 可用视角不足 {views_per_group}: {len(group_items)}"
            )
        selected_train.extend(chosen)

    evaluation_items = [item for item in parent["items"] if item["split"] in {"val", "test"}]
    selected_items = sorted(
        [*selected_train, *evaluation_items],
        key=lambda item: (FULL_SPLITS.index(str(item["split"])), str(item["source_image"])),
    )
    dataset_yaml_sha256 = parent["source_dataset_yaml_sha256"]
    manifest = {
        "schema_version": 1,
        "manifest_type": "grayprep-subset-index",
        "dataset_id": f"{parent['dataset_id']}-m",
        "source_dataset_yaml": parent["source_dataset_yaml"],
        "source_dataset_yaml_sha256": dataset_yaml_sha256,
        "source_semantics": "r_only",
        "class_names": names,
        "kpt_shape": [2, 3],
        "split_counts": _split_counts(selected_items),
        "item_count": len(selected_items),
        "source_revision": _source_revision(selected_items, dataset_yaml_sha256),
        "parent_manifest_sha256": sha256_file(parent_path),
        "selection": {
            "name": "medium-v1",
            "seed": seed,
            "train_policy": {
                "earth_groups": "all",
                "views_per_group": views_per_group,
                "empty_per_group_target": empty_per_group,
                "positive_fill": True,
                "moon_train": moon_train,
            },
            "evaluation_policy": "keep_complete_val_test",
        },
        "items": selected_items,
    }
    _validate_schema(manifest, schema_path)
    return manifest


def _ensure_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise PreprocessError(f"断点目录中的固定文件不一致: {path}")
        return
    atomic_write_bytes(path, payload)


def _item_signature(item: Mapping[str, Any], profile_hash: str) -> str:
    return canonical_json_sha256(
        {
            "source_image": item["source_image"],
            "source_image_size": item["source_image_size"],
            "source_image_mtime_ns": item["source_image_mtime_ns"],
            "source_label": item["source_label"],
            "source_label_sha256": item["source_label_sha256"],
            "profile_hash": profile_hash,
        }
    )


def _item_paths(staging: Path, item: Mapping[str, Any]) -> tuple[Path, Path, Path]:
    split = str(item["split"])
    stem = Path(str(item["source_image"])).stem
    return (
        staging / "images" / split / f"{stem}.png",
        staging / "labels" / split / f"{stem}.txt",
        staging / ".state" / split / f"{stem}.json",
    )


def _resume_record(
    staging: Path,
    item: Mapping[str, Any],
    *,
    root: Path,
    profile_hash: str,
) -> dict[str, Any] | None:
    output_image, output_label, state_path = _item_paths(staging, item)
    if not state_path.is_file():
        return None
    try:
        state = _load_json(state_path)
        record = state["record"]
        if state["signature"] != _item_signature(item, profile_hash):
            return None
        source_image = root / str(item["source_image"])
        source_label = root / str(item["source_label"])
        image_stat = source_image.stat()
        if image_stat.st_size != item["source_image_size"] or image_stat.st_mtime_ns != item["source_image_mtime_ns"]:
            return None
        if sha256_file(source_image) != record["source_image_sha256"]:
            return None
        if sha256_file(source_label) != item["source_label_sha256"]:
            return None
        if sha256_file(output_image) != record["output_image_sha256"]:
            return None
        if sha256_file(output_label) != record["output_label_sha256"]:
            return None
        return record
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return None


def _clear_incomplete_item(staging: Path, item: Mapping[str, Any]) -> None:
    for path in _item_paths(staging, item):
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".partial").unlink(missing_ok=True)


def _read_source_image(path: Path) -> tuple[np.ndarray, str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise PreprocessError(f"无法读取图片: {path}: {exc}") from exc
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise PreprocessError(f"无法解码图片: {path}")
    return image, hashlib.sha256(payload).hexdigest()


def _process_full_item(
    item: Mapping[str, Any],
    *,
    root: Path,
    staging: Path,
    net_spec: Any,
    profile_hash: str,
    resume: bool,
) -> dict[str, Any]:
    if resume:
        record = _resume_record(staging, item, root=root, profile_hash=profile_hash)
        if record is not None:
            return record
        _clear_incomplete_item(staging, item)

    source_image = root / str(item["source_image"])
    source_label = root / str(item["source_label"])
    image_stat = source_image.stat()
    if image_stat.st_size != item["source_image_size"] or image_stat.st_mtime_ns != item["source_image_mtime_ns"]:
        raise PreprocessError(f"源图片元数据已变化: {item['source_image']}")
    label_payload = source_label.read_bytes()
    if hashlib.sha256(label_payload).hexdigest() != item["source_label_sha256"]:
        raise PreprocessError(f"源标签已变化: {item['source_label']}")
    image, source_image_sha256 = _read_source_image(source_image)
    _require_r_only(image, str(item["source_image"]))
    source_height, source_width = image.shape[:2]
    label_text = label_payload.decode("utf-8")
    net_image = transform_image(image, "r_only", net_spec)
    net_label = transform_label_text(
        label_text,
        source_width=source_width,
        source_height=source_height,
        keypoint_count=2,
        spec=net_spec,
    )
    output_image, output_label, state_path = _item_paths(staging, item)
    write_gray_png(output_image, net_image)
    atomic_write_bytes(output_label, net_label.encode("utf-8"))
    record = {
        **item,
        "source_width": source_width,
        "source_height": source_height,
        "source_image_sha256": source_image_sha256,
        "output_image": output_image.relative_to(staging).as_posix(),
        "output_label": output_label.relative_to(staging).as_posix(),
        "output_image_sha256": sha256_file(output_image),
        "output_label_sha256": sha256_file(output_label),
        "resize_scale_x": net_spec.resize_width / source_width,
        "resize_scale_y": net_spec.resize_height / source_height,
        "padding": [net_spec.pad_left, net_spec.pad_top, net_spec.pad_right, net_spec.pad_bottom],
    }
    atomic_write_bytes(
        state_path,
        _json_bytes({"signature": _item_signature(item, profile_hash), "record": record}),
    )
    return record


def _initialize_full_worker(
    source_root: str,
    staging_root: str,
    net_profile: Mapping[str, Any],
    profile_hash: str,
    resume: bool,
    opencv_threads: int,
) -> None:
    cv2.setNumThreads(opencv_threads)
    _FULL_WORKER_STATE.clear()
    _FULL_WORKER_STATE.update(
        {
            "root": Path(source_root),
            "staging": Path(staging_root),
            "net_spec": spec_from_profile(net_profile),
            "profile_hash": profile_hash,
            "resume": resume,
        }
    )


def _process_full_item_worker(item: Mapping[str, Any]) -> dict[str, Any]:
    return _process_full_item(item, **_FULL_WORKER_STATE)


def _validate_full_output_paths(items: list[Mapping[str, Any]]) -> None:
    paths: list[str] = []
    for item in items:
        split = str(item["split"])
        stem = Path(str(item["source_image"])).stem
        paths.extend((f"images/{split}/{stem}.png", f"labels/{split}/{stem}.txt"))
    if len(paths) != len(set(paths)):
        raise PreprocessError("全量 manifest 中存在冲突的输出路径")


def build_full_dataset(
    source_root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    net_profile_path: str | os.PathLike[str],
    profile_schema_path: str | os.PathLike[str],
    manifest_schema_path: str | os.PathLike[str],
    workers: int = 1,
    opencv_threads: int | None = None,
    resume: bool = False,
) -> Path:
    """Build the full dataset into `<output>.partial`; verification publishes it."""

    _validate_parallel_settings(workers, opencv_threads)
    root = Path(source_root)
    destination = Path(output)
    staging = destination.with_name(destination.name + ".partial")
    if destination.exists():
        raise FileExistsError(f"正式输出已存在: {destination}")
    if staging.exists() and not resume:
        raise FileExistsError(f"暂存目录已存在；如需续跑请显式使用 --resume: {staging}")
    if staging.exists() and not staging.is_dir():
        raise PreprocessError(f"暂存路径不是目录: {staging}")

    manifest_path = Path(manifest_path)
    manifest = _load_json(manifest_path)
    _validate_schema(manifest, manifest_schema_path)
    if manifest.get("manifest_type") not in {"grayprep-full-index", "grayprep-subset-index"}:
        raise PreprocessError("输入不是 full/subset index manifest")
    if manifest.get("source_semantics") != "r_only":
        raise PreprocessError("全量构建只接受 r_only 源语义")
    if sha256_file(root / "dataset.yaml") != manifest["source_dataset_yaml_sha256"]:
        raise PreprocessError("源 dataset.yaml 与 full manifest 不一致")
    items = manifest.get("items")
    if not isinstance(items, list):
        raise PreprocessError("manifest items 必须是列表")
    _validate_full_output_paths(items)

    net_profile = _load_yaml(Path(net_profile_path))
    _validate_schema(net_profile, profile_schema_path)
    profile_hash = canonical_json_sha256(net_profile)
    net_spec = spec_from_profile(net_profile)
    staging.mkdir(parents=True, exist_ok=True)
    _ensure_bytes(staging / "source_manifest.json", _json_bytes(manifest))
    resolved = {
        "net1280": net_profile,
        "net1280_sha256": profile_hash,
        "source_manifest_sha256": sha256_file(manifest_path),
    }
    _ensure_bytes(
        staging / "profiles.resolved.yaml",
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True).encode("utf-8"),
    )

    try:
        if workers == 1:
            previous_threads = cv2.getNumThreads()
            try:
                if opencv_threads is not None:
                    cv2.setNumThreads(opencv_threads)
                output_items = [
                    _process_full_item(
                        item,
                        root=root,
                        staging=staging,
                        net_spec=net_spec,
                        profile_hash=profile_hash,
                        resume=resume,
                    )
                    for item in items
                ]
            finally:
                if opencv_threads is not None:
                    cv2.setNumThreads(previous_threads)
        else:
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=mp.get_context("spawn"),
                initializer=_initialize_full_worker,
                initargs=(str(root), str(staging), net_profile, profile_hash, resume, opencv_threads),
            ) as executor:
                output_items = list(executor.map(_process_full_item_worker, items, chunksize=1))
    except BaseException as exc:
        atomic_write_bytes(
            staging / "FAILED.json",
            _json_bytes({"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)}),
            overwrite=True,
        )
        raise

    statistics: dict[str, dict[str, Any]] = {}
    for split in FULL_SPLITS:
        split_items = [item for item in output_items if item["split"] == split]
        rows_per_class: Counter[int] = Counter()
        for item in split_items:
            rows_per_class.update(item["class_ids"])
        statistics[split] = {
            "images": len(split_items),
            "labels": len(split_items),
            "empty_labels": sum(bool(item["is_empty"]) for item in split_items),
            "groups": len({item["group_id"] for item in split_items}),
            "rows_per_class": {str(key): value for key, value in sorted(rows_per_class.items())},
        }
    output_manifest = {
        "schema_version": 1,
        "manifest_type": "grayprep-full-output",
        "dataset_id": manifest["dataset_id"],
        "source_revision": manifest["source_revision"],
        "source_semantics": "r_only",
        "output_semantics": "gray1",
        "class_names": manifest["class_names"],
        "kpt_shape": [2, 3],
        "profile_hashes": {"net1280": profile_hash},
        "item_count": len(output_items),
        "split_counts": statistics,
        "items": output_items,
    }
    atomic_write_bytes(staging / "manifest.json", _json_bytes(output_manifest), overwrite=True)
    atomic_write_bytes(staging / "class_statistics.json", _json_bytes(statistics), overwrite=True)
    dataset_yaml = {
        "path": ".",
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "kpt_shape": [2, 3],
        "flip_idx": [0, 1],
        "channels": 1,
        "input_semantics": "gray1",
        "names": manifest["class_names"],
    }
    atomic_write_bytes(
        staging / "dataset.yaml",
        yaml.safe_dump(dataset_yaml, sort_keys=False, allow_unicode=True).encode("utf-8"),
        overwrite=True,
    )
    atomic_write_bytes(
        staging / "transform_report.json",
        _json_bytes(
            {
                "status": "BUILT_PENDING_VERIFICATION",
                "items": len(output_items),
                "net_images": len(output_items),
                "labels": len(output_items),
                "fpga_bins": 0,
                "workers": workers,
                "opencv_threads": opencv_threads,
            }
        ),
        overwrite=True,
    )
    (staging / "FAILED.json").unlink(missing_ok=True)
    shutil.rmtree(staging / ".state", ignore_errors=True)
    _write_sha256sums(staging)
    return staging


def _initialize_verify_worker(
    output_root: str,
    source_root: str | None,
    net_profile: Mapping[str, Any],
    source_paths: set[str],
    class_count: int,
    opencv_threads: int,
) -> None:
    cv2.setNumThreads(opencv_threads)
    _VERIFY_WORKER_STATE.clear()
    _VERIFY_WORKER_STATE.update(
        {
            "output_root": Path(output_root),
            "source_root": Path(source_root) if source_root else None,
            "net_spec": spec_from_profile(net_profile),
            "source_paths": source_paths,
            "class_count": class_count,
        }
    )


def _verify_full_item(
    item: Mapping[str, Any],
    *,
    output_root: Path,
    source_root: Path | None,
    net_spec: Any,
    source_paths: set[str],
    class_count: int,
) -> dict[str, Any]:
    failures: list[str] = []
    output_image = output_root / str(item["output_image"])
    output_label = output_root / str(item["output_label"])
    try:
        if sha256_file(output_image) != item["output_image_sha256"]:
            failures.append(f"output_image_hash:{item['output_image']}")
        if sha256_file(output_label) != item["output_label_sha256"]:
            failures.append(f"output_label_hash:{item['output_label']}")
        image = cv2.imread(str(output_image), cv2.IMREAD_UNCHANGED)
        if image is None or image.shape != (1280, 1280) or image.dtype != np.uint8:
            failures.append(f"output_image_contract:{item['output_image']}")
        label_text = output_label.read_text(encoding="utf-8")
        for row in label_text.splitlines():
            if not row.strip():
                continue
            parsed = parse_label_line(row, keypoint_count=2)
            if parsed.class_id >= class_count:
                failures.append(f"output_class_id:{item['output_label']}")

        source_checked = False
        if source_root is not None and item["source_image"] in source_paths:
            source_checked = True
            source_image_path = source_root / str(item["source_image"])
            source_label_path = source_root / str(item["source_label"])
            source_image, source_hash = _read_source_image(source_image_path)
            if source_hash != item["source_image_sha256"]:
                failures.append(f"source_image_hash:{item['source_image']}")
            _require_r_only(source_image, str(item["source_image"]))
            expected_image = transform_image(source_image, "r_only", net_spec)
            if image is None or not np.array_equal(image, expected_image):
                failures.append(f"source_image_transform:{item['source_image']}")
            source_label_payload = source_label_path.read_bytes()
            if hashlib.sha256(source_label_payload).hexdigest() != item["source_label_sha256"]:
                failures.append(f"source_label_hash:{item['source_label']}")
            expected_label = transform_label_text(
                source_label_payload.decode("utf-8"),
                source_width=source_image.shape[1],
                source_height=source_image.shape[0],
                keypoint_count=2,
                spec=net_spec,
            )
            if label_text != expected_label:
                failures.append(f"source_label_transform:{item['source_label']}")
        return {"failures": failures, "source_checked": source_checked}
    except Exception as exc:
        return {
            "failures": [f"exception:{item.get('source_image')}:{type(exc).__name__}:{exc}"],
            "source_checked": False,
        }


def _verify_full_item_worker(item: Mapping[str, Any]) -> dict[str, Any]:
    return _verify_full_item(item, **_VERIFY_WORKER_STATE)


def _source_sample_paths(items: list[Mapping[str, Any]], sample: int) -> set[str]:
    paths = [str(item["source_image"]) for item in items]
    if sample < 0:
        raise PreprocessError("source_sample 不能小于 0")
    if sample == 0 or sample >= len(paths):
        return set(paths)
    return set(sorted(paths, key=lambda value: hashlib.sha256(value.encode()).digest())[:sample])


def verify_full_dataset(
    output: str | os.PathLike[str],
    *,
    net_profile_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str] | None = None,
    source_sample: int = 0,
    workers: int = 1,
    opencv_threads: int | None = None,
    publish: bool = False,
) -> dict[str, Any]:
    """Verify a staged or published full dataset and optionally publish it atomically."""

    _validate_parallel_settings(workers, opencv_threads)
    destination = Path(output)
    staging = destination.with_name(destination.name + ".partial")
    if publish:
        if source_root is None:
            raise PreprocessError("正式发布必须通过 --source 提供只读源数据进行复算")
        if destination.exists():
            raise FileExistsError(f"正式输出已存在，拒绝发布: {destination}")
        root = staging
    else:
        root = destination if destination.is_dir() else staging
    if not root.is_dir():
        raise PreprocessError(f"待验证目录不存在: {root}")
    if (root / ".state").exists():
        raise PreprocessError("构建尚未完成，存在 .state")

    manifest = _load_json(root / "manifest.json")
    if manifest.get("manifest_type") != "grayprep-full-output":
        raise PreprocessError("输出 manifest 类型错误")
    items = manifest.get("items")
    if not isinstance(items, list) or len(items) != manifest.get("item_count"):
        raise PreprocessError("输出 manifest item_count 不一致")
    net_profile = _load_yaml(Path(net_profile_path))
    profile_hash = canonical_json_sha256(net_profile)
    if manifest.get("profile_hashes", {}).get("net1280") != profile_hash:
        raise PreprocessError("net1280 配置与输出 manifest 不一致")

    sums: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        sums[relative] = expected
    output_paths = {
        str(item[key])
        for item in items
        for key in ("output_image", "output_label")
    }
    failures: list[str] = []
    for item in items:
        for path_key, hash_key in (
            ("output_image", "output_image_sha256"),
            ("output_label", "output_label_sha256"),
        ):
            if sums.get(str(item[path_key])) != item[hash_key]:
                failures.append(f"sha256sums_manifest:{item[path_key]}")
    for relative, expected in sums.items():
        if relative in output_paths:
            continue
        path = root / relative
        if not path.is_file() or sha256_file(path) != expected:
            failures.append(f"metadata_hash:{relative}")

    names = manifest["class_names"]
    split_counts = {split: Counter() for split in FULL_SPLITS}
    groups_by_split = {split: set() for split in FULL_SPLITS}
    paths_seen: set[str] = set()
    for item in items:
        split = item["split"]
        if split not in FULL_SPLITS:
            failures.append(f"split:{split}")
            continue
        groups_by_split[split].add(item["group_id"])
        split_counts[split].update(item["class_ids"])
        for key in ("output_image", "output_label"):
            path = str(item[key])
            if path in paths_seen:
                failures.append(f"duplicate_output:{path}")
            paths_seen.add(path)
    expected_classes = set(range(len(names)))
    for split in FULL_SPLITS:
        if set(split_counts[split]) != expected_classes:
            failures.append(f"class_coverage:{split}")
    for index, left in enumerate(FULL_SPLITS):
        for right in FULL_SPLITS[index + 1 :]:
            overlap = groups_by_split[left] & groups_by_split[right]
            if overlap:
                failures.append(f"group_overlap:{left}:{right}:{sorted(overlap)[:5]}")
    partial_files = [path.relative_to(root).as_posix() for path in root.rglob("*.partial")]
    if partial_files:
        failures.append(f"partial_files:{partial_files[:5]}")

    source_paths = _source_sample_paths(items, source_sample) if source_root is not None else set()
    if source_root is None and source_sample:
        raise PreprocessError("指定 source_sample 时必须同时指定 source_root")
    if workers == 1:
        previous_threads = cv2.getNumThreads()
        try:
            if opencv_threads is not None:
                cv2.setNumThreads(opencv_threads)
            results = [
                _verify_full_item(
                    item,
                    output_root=root,
                    source_root=Path(source_root) if source_root is not None else None,
                    net_spec=spec_from_profile(net_profile),
                    source_paths=source_paths,
                    class_count=len(names),
                )
                for item in items
            ]
        finally:
            if opencv_threads is not None:
                cv2.setNumThreads(previous_threads)
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp.get_context("spawn"),
            initializer=_initialize_verify_worker,
            initargs=(str(root), str(source_root) if source_root is not None else None, net_profile, source_paths, len(names), opencv_threads),
        ) as executor:
            results = list(executor.map(_verify_full_item_worker, items, chunksize=1))
    for result in results:
        failures.extend(result["failures"])
    report = {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "items_checked": len(items),
        "hashes_checked": len(sums),
        "source_items_checked": sum(bool(result["source_checked"]) for result in results),
        "class_count": len(names),
        "split_counts": {
            split: {str(key): value for key, value in sorted(counts.items())}
            for split, counts in split_counts.items()
        },
        "published": False,
    }
    if failures:
        raise PreprocessError(f"full dataset 验证失败，共 {len(failures)} 项: {failures[:20]}")
    if publish:
        atomic_write_bytes(root / "verification_report.json", _json_bytes(report))
        verified = {
            "status": "PASS",
            "manifest_sha256": sha256_file(root / "manifest.json"),
            "sha256sums_sha256": sha256_file(root / "SHA256SUMS"),
            "verification_report_sha256": sha256_file(root / "verification_report.json"),
            "source_items_checked": report["source_items_checked"],
        }
        atomic_write_bytes(root / "VERIFIED", _json_bytes(verified))
        os.replace(root, destination)
        report["published"] = True
        report["output"] = str(destination)
    else:
        report["output"] = str(root)
    return report
