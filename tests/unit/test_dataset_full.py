from __future__ import annotations

from pathlib import Path
import tempfile
from unittest import mock
import unittest

import cv2
import numpy as np
import yaml

from grayprep.dataset_full import (
    build_full_dataset,
    create_full_manifest,
    verify_full_dataset,
    write_full_manifest,
)
from grayprep.pipelines.common import PreprocessError


class FullDatasetTest(unittest.TestCase):
    def _repository(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _create_source(self, root: Path, *, overlapping_groups: bool = False) -> None:
        dataset = {
            "path": str(root),
            "train": "images/train",
            "val": "images/val",
            "test": "images/test",
            "kpt_shape": [2, 3],
            "flip_idx": [0, 1],
            "r_channel_only": True,
            "names": ["a", "b"],
        }
        (root / "dataset.yaml").write_text(
            yaml.safe_dump(dataset, sort_keys=False), encoding="utf-8"
        )
        for split_index, split in enumerate(("train", "val", "test")):
            (root / "images" / split).mkdir(parents=True)
            (root / "labels" / split).mkdir(parents=True)
            prefix = "same" if overlapping_groups else split
            for class_id, class_name in enumerate(("a", "b")):
                stem = f"{prefix}_{class_name}_000_view_01"
                image = np.zeros((8, 8, 3), dtype=np.uint8)
                image[:, :, 2] = 40 + split_index * 20 + class_id
                cv2.imwrite(str(root / "images" / split / f"{stem}.png"), image)
                (root / "labels" / split / f"{stem}.txt").write_text(
                    f"{class_id} 0.5 0.5 0.25 0.25 0.4 0.4 2 0.6 0.6 2\n",
                    encoding="utf-8",
                )
            empty_stem = f"{prefix}_background_000_view_01"
            image = np.zeros((8, 8, 3), dtype=np.uint8)
            image[:, :, 2] = 10 + split_index
            cv2.imwrite(str(root / "images" / split / f"{empty_stem}.png"), image)
            (root / "labels" / split / f"{empty_stem}.txt").write_text("", encoding="utf-8")

    def _index(self, source: Path, manifest_path: Path) -> dict:
        manifest = create_full_manifest(
            source,
            schema_path=self._repository() / "schemas/full-dataset-manifest.schema.json",
        )
        write_full_manifest(manifest_path, manifest)
        return manifest

    def test_index_build_verify_and_publish_full_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            self._create_source(source)
            manifest_path = root / "full-index.json"
            first = self._index(source, manifest_path)
            second = create_full_manifest(
                source,
                schema_path=self._repository() / "schemas/full-dataset-manifest.schema.json",
            )
            self.assertEqual(first, second)
            self.assertEqual(first["item_count"], 9)
            self.assertEqual(first["split_counts"]["train"]["empty_labels"], 1)
            self.assertEqual(first["items"][0]["group_id"], "train_a_000")

            output = root / "prepared"
            staging = build_full_dataset(
                source,
                manifest_path,
                output,
                net_profile_path=self._repository() / "configs/net1280.yaml",
                profile_schema_path=self._repository() / "schemas/preprocess-profile.schema.json",
                manifest_schema_path=self._repository() / "schemas/full-dataset-manifest.schema.json",
                workers=2,
                opencv_threads=1,
            )
            self.assertEqual(staging, output.with_name("prepared.partial"))
            self.assertTrue(staging.is_dir())
            self.assertFalse(output.exists())
            self.assertFalse((staging / ".state").exists())
            self.assertEqual(list(staging.rglob("*.bin")), [])

            report = verify_full_dataset(
                output,
                net_profile_path=self._repository() / "configs/net1280.yaml",
                source_root=source,
                source_sample=0,
                workers=2,
                opencv_threads=1,
                publish=True,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["published"])
            self.assertEqual(report["source_items_checked"], 9)
            self.assertTrue((output / "VERIFIED").is_file())
            self.assertFalse(staging.exists())
            sample = cv2.imread(
                str(next((output / "images" / "train").glob("*.png"))),
                cv2.IMREAD_UNCHANGED,
            )
            self.assertEqual(sample.shape, (1280, 1280))

            second_report = verify_full_dataset(
                output,
                net_profile_path=self._repository() / "configs/net1280.yaml",
                workers=2,
                opencv_threads=1,
            )
            self.assertEqual(second_report["status"], "PASS")

    def test_failed_build_keeps_staging_and_resume_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            self._create_source(source)
            manifest_path = root / "full-index.json"
            self._index(source, manifest_path)
            output = root / "prepared"
            kwargs = {
                "net_profile_path": self._repository() / "configs/net1280.yaml",
                "profile_schema_path": self._repository() / "schemas/preprocess-profile.schema.json",
                "manifest_schema_path": self._repository() / "schemas/full-dataset-manifest.schema.json",
                "workers": 1,
                "opencv_threads": 1,
            }
            with mock.patch(
                "grayprep.dataset_full._process_full_item",
                side_effect=PreprocessError("injected failure"),
            ):
                with self.assertRaisesRegex(PreprocessError, "injected failure"):
                    build_full_dataset(source, manifest_path, output, **kwargs)
            staging = output.with_name("prepared.partial")
            self.assertTrue((staging / "FAILED.json").is_file())
            with self.assertRaises(FileExistsError):
                build_full_dataset(source, manifest_path, output, **kwargs)
            completed = build_full_dataset(source, manifest_path, output, resume=True, **kwargs)
            self.assertEqual(completed, staging)
            self.assertFalse((staging / "FAILED.json").exists())

    def test_index_rejects_group_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            self._create_source(source, overlapping_groups=True)
            with self.assertRaisesRegex(PreprocessError, "group 跨 split"):
                create_full_manifest(
                    source,
                    schema_path=self._repository() / "schemas/full-dataset-manifest.schema.json",
                )

    def test_index_rejects_missing_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            self._create_source(source)
            next((source / "labels" / "train").glob("*.txt")).unlink()
            with self.assertRaisesRegex(PreprocessError, "图片缺少标签"):
                create_full_manifest(
                    source,
                    schema_path=self._repository() / "schemas/full-dataset-manifest.schema.json",
                )

    def test_publish_requires_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing"
            with self.assertRaisesRegex(PreprocessError, "正式发布必须"):
                verify_full_dataset(
                    output,
                    net_profile_path=self._repository() / "configs/net1280.yaml",
                    publish=True,
                )


if __name__ == "__main__":
    unittest.main()
