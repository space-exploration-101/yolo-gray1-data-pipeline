from __future__ import annotations

import unittest

import numpy as np

from grayprep.pipelines.common import PreprocessError
from grayprep.pipelines.net1280 import (
    Net1280Spec,
    format_label,
    parse_label_line,
    spec_from_profile,
    transform_image,
    transform_label,
    transform_label_text,
    transform_summary,
)


class Net1280ImageTest(unittest.TestCase):
    def test_output_shape_channel_and_padding(self) -> None:
        source = np.full((20, 20), 77, dtype=np.uint8)
        output = transform_image(source, "native_gray")
        self.assertEqual(output.shape, (1280, 1280))
        self.assertEqual(output.dtype, np.uint8)
        self.assertTrue(np.all(output[:140, :] == 0))
        self.assertTrue(np.all(output[-140:, :] == 0))
        self.assertTrue(np.all(output[:, :140] == 0))
        self.assertTrue(np.all(output[:, -140:] == 0))
        self.assertTrue(np.all(output[140:1140, 140:1140] == 77))

    def test_r_only_image_remains_bright(self) -> None:
        source = np.zeros((10, 10, 3), dtype=np.uint8)
        source[:, :, 2] = 200
        output = transform_image(source, "r_only")
        self.assertEqual(int(output[640, 640]), 200)

    def test_invalid_spec_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            transform_image(
                np.zeros((2, 2), dtype=np.uint8),
                "native_gray",
                Net1280Spec(output_width=1279),
            )


class Net1280LabelTest(unittest.TestCase):
    def test_known_label_transform(self) -> None:
        source = "3 0.5 0.5 0.2 0.4 0.25 0.75 2 0 0 0"
        expected = (
            "3 0.50000000 0.50000000 0.15625000 0.31250000 "
            "0.30468750 0.69531250 2 0.00000000 0.00000000 0\n"
        )
        self.assertEqual(
            transform_label_text(source, source_width=4096, source_height=4096),
            expected,
        )

    def test_existing_11_column_shape_is_preserved(self) -> None:
        source = "0 0.208130 0.494019 0.285400 0.507568 0.208130 0.494019 2 0.208130 0.494019 2"
        output = transform_label_text(source, source_width=4096, source_height=4096)
        self.assertEqual(len(output.split()), 11)

    def test_multiple_rows_and_blank_lines(self) -> None:
        row = "1 0.5 0.5 0.1 0.1 0.4 0.4 2 0.6 0.6 2"
        output = transform_label_text(f"{row}\n\n{row}\n", source_width=2048, source_height=2048)
        self.assertEqual(len(output.strip().splitlines()), 2)
        self.assertTrue(output.endswith("\n"))

    def test_bad_column_count_has_line_number(self) -> None:
        with self.assertRaisesRegex(PreprocessError, "第 1 行"):
            transform_label_text("0 0.5", source_width=10, source_height=10)

    def test_out_of_range_visible_keypoint_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            parse_label_line("0 0.5 0.5 0.1 0.1 1.1 0.5 2 0.5 0.5 2")

    def test_invisible_zero_sentinel_is_preserved(self) -> None:
        parsed = parse_label_line("0 0.5 0.5 0.1 0.1 0 0 0 0.5 0.5 2")
        transformed = transform_label(
            parsed, source_width=4096, source_height=4096
        )
        self.assertEqual(transformed.keypoints[0].x, 0)
        self.assertEqual(transformed.keypoints[0].y, 0)
        self.assertEqual(transformed.keypoints[0].visibility, 0)

    def test_format_is_deterministic(self) -> None:
        parsed = parse_label_line("2 0.5 0.5 0.2 0.2 0.1 0.2 2 0.3 0.4 1")
        self.assertEqual(format_label(parsed), format_label(parsed))


class Net1280ConfigTest(unittest.TestCase):
    def test_profile_mapping(self) -> None:
        profile = {
            "name": "net1280",
            "resize": {
                "width": 1000,
                "height": 1000,
                "interpolation_down": "area",
                "interpolation_up": "linear",
            },
            "padding": {
                "left": 140,
                "right": 140,
                "top": 140,
                "bottom": 140,
                "value": 0,
            },
            "output": {"width": 1280, "height": 1280},
        }
        self.assertEqual(spec_from_profile(profile), Net1280Spec())

    def test_summary_for_4096_source(self) -> None:
        summary = transform_summary(source_width=4096, source_height=4096)
        self.assertEqual(summary["scale_x"], 1000 / 4096)
        self.assertEqual(summary["padding"]["left"], 140)
        self.assertEqual(summary["output_channels"], 1)


if __name__ == "__main__":
    unittest.main()
