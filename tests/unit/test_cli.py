import unittest

from grayprep.cli import main


class CliTest(unittest.TestCase):
    def test_list(self) -> None:
        self.assertEqual(main(["list"]), 0)


if __name__ == "__main__":
    unittest.main()
