from unittest import mock
import unittest

from grayprep.cli import main


class CliTest(unittest.TestCase):
    def test_list(self) -> None:
        self.assertEqual(main(["list"]), 0)

    @mock.patch("grayprep.cli.build_smoke_dataset")
    def test_build_smoke_passes_parallel_settings(self, build: mock.Mock) -> None:
        build.return_value = "/tmp/output"
        result = main(
            [
                "dataset", "build-smoke",
                "--source", "/source",
                "--manifest", "/manifest.json",
                "--output", "/output",
                "--net-config", "/net.yaml",
                "--cam-config", "/cam.yaml",
                "--schema", "/schema.json",
                "--workers", "32",
                "--opencv-threads", "1",
            ]
        )
        self.assertEqual(result, 0)
        self.assertEqual(build.call_args.kwargs["workers"], 32)
        self.assertEqual(build.call_args.kwargs["opencv_threads"], 1)


if __name__ == "__main__":
    unittest.main()
