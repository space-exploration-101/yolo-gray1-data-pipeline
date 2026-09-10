from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[2]


class ProfileSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            (ROOT / "schemas/preprocess-profile.schema.json").read_text(encoding="utf-8")
        )
        cls.validator = Draft202012Validator(cls.schema)

    def test_schema_itself_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.schema)

    def test_net1280_profile(self) -> None:
        profile = yaml.safe_load(
            (ROOT / "configs/net1280.yaml").read_text(encoding="utf-8")
        )
        self.validator.validate(profile)

    def test_cam2000_accepted_profile(self) -> None:
        profile = yaml.safe_load(
            (ROOT / "configs/cam2000.yaml").read_text(encoding="utf-8")
        )
        self.validator.validate(profile)


if __name__ == "__main__":
    unittest.main()
