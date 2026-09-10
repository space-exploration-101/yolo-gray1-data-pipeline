from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import unittest

import numpy as np

from grayprep.pipelines.cam2000 import Cam2000Spec, decode_frame, encode_frame


ROOT = Path(__file__).resolve().parent
EXPECTED = json.loads(
    (ROOT / "expected/fpga-validated-frame-001.json").read_text(encoding="utf-8")
)


class FpgaGoldenBinTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("GRAYPREP_FPGA_GOLDEN_BIN")
        if not configured:
            raise unittest.SkipTest(
                "设置 GRAYPREP_FPGA_GOLDEN_BIN 后运行外部 FPGA golden bin 测试"
            )
        cls.path = Path(configured)
        if not cls.path.is_file():
            raise AssertionError(f"FPGA golden bin 不存在: {cls.path}")

    def test_fpga_validated_frame_is_byte_exact(self) -> None:
        payload = self.path.read_bytes()
        self.assertEqual(len(payload), EXPECTED["file_size"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), EXPECTED["sha256"])

        spec = Cam2000Spec()
        rows = np.frombuffer(payload, dtype=np.uint8).reshape(
            spec.height, spec.bytes_per_row
        )
        self.assertEqual(
            int(np.count_nonzero(rows[:, spec.active_bytes_per_row :])), 0
        )

        decoded = decode_frame(payload, spec, verify_padding=True)
        self.assertEqual(list(decoded.shape), EXPECTED["decoded_shape"])
        self.assertEqual(str(decoded.dtype), EXPECTED["decoded_dtype"])
        self.assertEqual(
            hashlib.sha256(decoded.tobytes()).hexdigest(),
            EXPECTED["decoded_samples_sha256"],
        )
        self.assertEqual(encode_frame(decoded, spec), payload)


if __name__ == "__main__":
    unittest.main()
