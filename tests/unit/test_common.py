from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from grayprep.pipelines.common import (
    PreprocessError,
    atomic_write_bytes,
    canonical_json_sha256,
    image_metadata,
    load_gray1,
    resize_gray1,
    sha256_file,
    to_gray1,
    write_gray_png,
)


class GraySemanticsTest(unittest.TestCase):
    def test_native_gray_is_preserved(self) -> None:
        source = np.arange(12, dtype=np.uint8).reshape(3, 4)
        actual = to_gray1(source, "native_gray")
        np.testing.assert_array_equal(actual, source)
        self.assertTrue(actual.flags.c_contiguous)

    def test_r_only_reads_bgr_red_plane(self) -> None:
        source = np.zeros((2, 3, 3), dtype=np.uint8)
        source[:, :, 0] = 7
        source[:, :, 1] = 11
        source[:, :, 2] = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
        np.testing.assert_array_equal(to_gray1(source, "r_only"), source[:, :, 2])

    def test_color_to_gray_uses_opencv_bgr_contract(self) -> None:
        source = np.array([[[10, 20, 200], [200, 20, 10]]], dtype=np.uint8)
        expected = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        np.testing.assert_array_equal(to_gray1(source, "color_to_gray"), expected)

    def test_ambiguous_native_gray_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            to_gray1(np.zeros((2, 2, 3), dtype=np.uint8), "native_gray")

    def test_non_uint8_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            to_gray1(np.zeros((2, 2), dtype=np.uint16), "native_gray")


class ResizeAndIoTest(unittest.TestCase):
    def test_resize_shape_and_dtype(self) -> None:
        source = np.arange(64, dtype=np.uint8).reshape(8, 8)
        actual = resize_gray1(source, width=4, height=5)
        self.assertEqual(actual.shape, (5, 4))
        self.assertEqual(actual.dtype, np.uint8)

    def test_invalid_resize_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            resize_gray1(np.zeros((2, 2), dtype=np.uint8), width=0, height=2)

    def test_unicode_png_roundtrip_is_single_channel(self) -> None:
        source = np.arange(35, dtype=np.uint8).reshape(5, 7)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "灰度样例.png"
            write_gray_png(path, source)
            actual = load_gray1(path, "native_gray")
            np.testing.assert_array_equal(actual, source)
            self.assertFalse(path.with_name(path.name + ".partial").exists())

    def test_atomic_write_refuses_overwrite_and_leaves_no_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.dat"
            atomic_write_bytes(path, b"first")
            with self.assertRaises(FileExistsError):
                atomic_write_bytes(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")
            self.assertFalse(path.with_name(path.name + ".partial").exists())


class MetadataTest(unittest.TestCase):
    def test_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x"
            path.write_bytes(b"gray1")
            self.assertEqual(sha256_file(path), hashlib.sha256(b"gray1").hexdigest())

    def test_canonical_hash_ignores_mapping_order(self) -> None:
        self.assertEqual(
            canonical_json_sha256({"a": 1, "b": 2}),
            canonical_json_sha256({"b": 2, "a": 1}),
        )

    def test_image_metadata(self) -> None:
        source = np.array([[0, 2], [4, 255]], dtype=np.uint8)
        self.assertEqual(
            image_metadata(source),
            {
                "width": 2,
                "height": 2,
                "channels": 1,
                "dtype": "uint8",
                "min": 0,
                "max": 255,
            },
        )


if __name__ == "__main__":
    unittest.main()
