from pathlib import Path
import tomllib

import grayprep


ROOT = Path(__file__).resolve().parents[2]


def test_package_version_matches_project_metadata() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert grayprep.__version__ == metadata["project"]["version"]
    assert grayprep.__version__ == "0.1.0"
