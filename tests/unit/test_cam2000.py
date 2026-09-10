from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from grayprep.pipelines.cam2000 import (
    BYTE_ORDER_ID,
    PACKING_ID,
    U8_TO_U12_ID,
    Cam2000Spec,
    decode_frame,
    encode_frame,
    pack_12bit_to_bytes,
    protocol_summary,
    spec_from_profile,
    transform_image_to_u12,
    transform_point_to_cam2000,
    u12_to_u8,
    u8_to_u12,
    unpack_12bit_from_bytes,
    write_camera_bin,
)
from grayprep.pipelines.common import PreprocessError


class CameraValueMappingTest(unittest.TestCase):
    def test_all_u8_values_roundtrip_exactly(self) -> None:
        source = np.arange(256, dtype=np.uint8)
        np.testing.assert_array_equal(u12_to_u8(u8_to_u12(source)), source)

    def test_selected_full_range_values(self) -> None:
        source = np.array([0, 1, 2, 127, 128, 254, 255], dtype=np.uint8)
        expected = np.array([0, 16, 32, 2039, 2056, 4079, 4095], dtype=np.uint16)
        np.testing.assert_array_equal(u8_to_u12(source), expected)

    def test_out_of_range_u12_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            u12_to_u8(np.array([4096], dtype=np.uint16))


class CameraPackingTest(unittest.TestCase):
    def test_known_pair_abc_123(self) -> None:
        packed = pack_12bit_to_bytes(np.array([0xABC, 0x123], dtype=np.uint16))
        self.assertEqual(packed, bytes.fromhex("BC 3A 12"))
        np.testing.assert_array_equal(
            unpack_12bit_from_bytes(packed), np.array([0xABC, 0x123], dtype=np.uint16)
        )

    def test_extreme_pairs(self) -> None:
        self.assertEqual(
            pack_12bit_to_bytes(np.array([0, 4095], dtype=np.uint16)),
            bytes.fromhex("00 F0 FF"),
        )
        self.assertEqual(
            pack_12bit_to_bytes(np.array([4095, 0], dtype=np.uint16)),
            bytes.fromhex("FF 0F 00"),
        )

    def test_malformed_payload_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            unpack_12bit_from_bytes(b"\x00\x01")


class CameraFrameTest(unittest.TestCase):
    def test_full_frame_layout_padding_and_roundtrip(self) -> None:
        spec = Cam2000Spec()
        frame = np.zeros((spec.height, spec.width), dtype=np.uint16)
        frame[0, :4] = [0xABC, 0x123, 0, 4095]
        frame[-1, -2:] = [4095, 0]
        payload = encode_frame(frame, spec)

        self.assertEqual(len(payload), 8_192_000)
        self.assertEqual(payload[:6], bytes.fromhex("BC 3A 12 00 F0 FF"))
        rows = np.frombuffer(payload, dtype=np.uint8).reshape(2000, 4096)
        self.assertTrue(np.all(rows[:, 3000:] == 0))
        np.testing.assert_array_equal(decode_frame(payload, spec), frame)

    def test_nonzero_padding_is_rejected(self) -> None:
        spec = Cam2000Spec()
        payload = bytearray(encode_frame(np.zeros((2000, 2000), dtype=np.uint16), spec))
        payload[3000] = 1
        with self.assertRaises(PreprocessError):
            decode_frame(payload, spec)

    def test_wrong_file_size_is_rejected(self) -> None:
        with self.assertRaises(PreprocessError):
            decode_frame(b"\x00" * 10)

    def test_atomic_file_publish_and_roundtrip(self) -> None:
        spec = Cam2000Spec()
        frame = np.zeros((2000, 2000), dtype=np.uint16)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "frame.bin"
            write_camera_bin(output, frame, spec)
            self.assertEqual(output.stat().st_size, 8_192_000)
            self.assertFalse(Path(str(output) + ".partial").exists())


class CameraImageAndGeometryTest(unittest.TestCase):
    def test_color_png_semantics_and_linear_resize(self) -> None:
        source = np.array(
            [
                [[0, 0, 255], [0, 255, 0]],
                [[255, 0, 0], [255, 255, 255]],
            ],
            dtype=np.uint8,
        )
        spec = Cam2000Spec(width=4, height=4, bytes_per_row=8, expected_file_bytes=32)
        expected_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        expected = cv2.resize(expected_gray, (4, 4), interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(
            transform_image_to_u12(source, "color_to_gray", spec), u8_to_u12(expected)
        )

    def test_float_centroid_is_scaled_without_rounding(self) -> None:
        actual = transform_point_to_cam2000(
            560.5, 738.25, source_width=2048, source_height=2048
        )
        self.assertEqual(actual, (547.36328125, 720.947265625))

    def test_protocol_summary_matches_signed_numbers(self) -> None:
        summary = protocol_summary()
        self.assertEqual(summary["active_bytes_per_row"], 3000)
        self.assertEqual(summary["padding_bytes_per_row"], 1096)
        self.assertEqual(summary["active_bytes_total"], 6_000_000)
        self.assertEqual(summary["padding_bytes_total"], 2_192_000)
        self.assertEqual(summary["expected_file_bytes"], 8_192_000)

    def test_profile_mapping(self) -> None:
        profile = {
            "name": "cam2000",
            "resize": {
                "width": 2000,
                "height": 2000,
                "interpolation_down": "linear",
                "interpolation_up": "linear",
            },
            "camera": {
                "width": 2000,
                "height": 2000,
                "bit_depth": 12,
                "bytes_per_row": 4096,
                "expected_file_bytes": 8_192_000,
                "sample_packing": PACKING_ID,
                "byte_order": BYTE_ORDER_ID,
                "uint8_to_uint12": U8_TO_U12_ID,
                "row_tail_value": 0,
                "header_bytes": 0,
                "trailer_bytes": 0,
            },
        }
        self.assertEqual(spec_from_profile(profile), Cam2000Spec())


if __name__ == "__main__":
    unittest.main()
