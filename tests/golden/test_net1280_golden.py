from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from grayprep.pipelines.common import read_image
from grayprep.pipelines.net1280 import transform_image, transform_label_text


ROOT = Path(__file__).resolve().parent


class Net1280GoldenTest(unittest.TestCase):
    def test_synthetic_image_and_label(self) -> None:
        source_image = read_image(ROOT / "fixtures/net1280_source.pgm")
        output_image = transform_image(source_image, "native_gray")
        source_label = (ROOT / "fixtures/net1280_source.txt").read_text()
        expected_label = (ROOT / "expected/net1280_label.txt").read_text()
        output_label = transform_label_text(
            source_label, source_width=source_image.shape[1], source_height=source_image.shape[0]
        )

        self.assertEqual(output_image.shape, (1280, 1280))
        self.assertEqual(output_image.dtype, np.uint8)
        self.assertTrue(np.all(output_image[:140, :] == 0))
        self.assertTrue(np.all(output_image[:, :140] == 0))
        self.assertEqual(output_label, expected_label)


if __name__ == "__main__":
    unittest.main()
