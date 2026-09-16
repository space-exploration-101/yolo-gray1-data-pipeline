from __future__ import annotations

from pathlib import Path
import json
import tempfile
from unittest import mock
import unittest

import cv2
import numpy as np
import yaml
from jsonschema import Draft202012Validator

from grayprep.dataset_smoke import (
    _validate_parallel_settings,
    _validate_unique_output_paths,
    build_smoke_dataset,
    create_smoke_manifest,
    write_selection_manifest,
)
from grayprep.pipelines.common import PreprocessError


class SmokeSelectionTest(unittest.TestCase):
    def test_parallel_settings_require_explicit_positive_values(self) -> None:
        _validate_parallel_settings(1, None)
        _validate_parallel_settings(32, 1)
        with self.assertRaises(PreprocessError):
            _validate_parallel_settings(0, 1)
        with self.assertRaises(PreprocessError):
            _validate_parallel_settings(2, None)
        with self.assertRaises(PreprocessError):
            _validate_parallel_settings(2, 0)

    def test_parallel_output_paths_must_be_unique(self) -> None:
        item = {"split": "train", "source_image": "images/train/a.png"}
        with self.assertRaises(PreprocessError):
            _validate_unique_output_paths([item, item])

    def test_selection_is_deterministic_and_train_calibration_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dataset.yaml").write_text(yaml.safe_dump({"r_channel_only": True, "names": ["a", "b"]}))
            for split in ("train", "val", "test"):
                (root / "images" / split).mkdir(parents=True)
                (root / "labels" / split).mkdir(parents=True)
                count = 3 if split == "train" else 2
                for class_id in (0, 1):
                    for index in range(count):
                        stem = f"{split}_{class_id}_{index}"
                        image = np.zeros((4, 4, 3), dtype=np.uint8)
                        image[:, :, 2] = class_id * 10 + index
                        cv2.imwrite(str(root / "images" / split / f"{stem}.png"), image)
                        (root / "labels" / split / f"{stem}.txt").write_text(
                            f"{class_id} 0.5 0.5 0.2 0.2 0.4 0.4 2 0.6 0.6 2\n"
                        )
            first = create_smoke_manifest(root, seed=17, per_class=1)
            second = create_smoke_manifest(root, seed=17, per_class=1)
            self.assertEqual(first, second)
            self.assertEqual(first["item_count"], 8)
            paths = [item["source_image"] for item in first["items"]]
            self.assertEqual(len(paths), len(set(paths)))
            self.assertEqual({item["split"] for item in first["items"]}, {"train", "val", "test", "calibration"})

            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas/dataset-manifest.schema.json").read_text()
            )
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(first)

            manifest_path = root / "selection.json"
            write_selection_manifest(manifest_path, first)
            output = root / "failed-output"
            repository = Path(__file__).resolve().parents[2]
            with mock.patch(
                "grayprep.dataset_smoke._process_smoke_item",
                side_effect=PreprocessError("injected worker failure"),
            ):
                with self.assertRaisesRegex(PreprocessError, "injected worker failure"):
                    build_smoke_dataset(
                        root,
                        manifest_path,
                        output,
                        net_profile_path=repository / "configs/net1280.yaml",
                        cam_profile_path=repository / "configs/cam2000.yaml",
                        schema_path=repository / "schemas/preprocess-profile.schema.json",
                        workers=1,
                        opencv_threads=1,
                    )
            self.assertFalse(output.exists())
            self.assertFalse(output.with_name(output.name + ".partial").exists())


if __name__ == "__main__":
    unittest.main()
