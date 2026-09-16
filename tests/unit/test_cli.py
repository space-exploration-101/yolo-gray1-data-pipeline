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

    @mock.patch("grayprep.cli.write_full_manifest")
    @mock.patch("grayprep.cli.create_full_manifest")
    def test_index_full_writes_manifest(self, create: mock.Mock, write: mock.Mock) -> None:
        create.return_value = {"item_count": 9, "source_revision": "a" * 64}
        result = main(
            [
                "dataset", "index-full",
                "--source", "/source",
                "--output", "/full-index.json",
                "--schema", "/full-schema.json",
            ]
        )
        self.assertEqual(result, 0)
        create.assert_called_once_with("/source", schema_path="/full-schema.json")
        write.assert_called_once_with("/full-index.json", create.return_value)

    @mock.patch("grayprep.cli.build_full_dataset")
    def test_build_full_passes_resume_and_parallel_settings(self, build: mock.Mock) -> None:
        build.return_value = "/output.partial"
        result = main(
            [
                "dataset", "build-full",
                "--source", "/source",
                "--manifest", "/full-index.json",
                "--output", "/output",
                "--net-config", "/net.yaml",
                "--profile-schema", "/profile-schema.json",
                "--manifest-schema", "/full-schema.json",
                "--workers", "32",
                "--opencv-threads", "1",
                "--resume",
            ]
        )
        self.assertEqual(result, 0)
        self.assertEqual(build.call_args.kwargs["workers"], 32)
        self.assertEqual(build.call_args.kwargs["opencv_threads"], 1)
        self.assertTrue(build.call_args.kwargs["resume"])

    @mock.patch("grayprep.cli.write_full_manifest")
    @mock.patch("grayprep.cli.create_medium_manifest")
    def test_select_medium_passes_policy(self, create: mock.Mock, write: mock.Mock) -> None:
        create.return_value = {
            "item_count": 100,
            "split_counts": {},
            "source_revision": "a" * 64,
        }
        result = main(
            [
                "dataset", "select-medium",
                "--manifest", "/full.json",
                "--output", "/medium.json",
                "--schema", "/schema.json",
                "--seed", "medium-v1",
                "--views-per-group", "10",
                "--empty-per-group", "2",
                "--moon-train", "600",
            ]
        )
        self.assertEqual(result, 0)
        self.assertEqual(create.call_args.kwargs["views_per_group"], 10)
        self.assertEqual(create.call_args.kwargs["empty_per_group"], 2)
        self.assertEqual(create.call_args.kwargs["moon_train"], 600)
        write.assert_called_once_with("/medium.json", create.return_value)

    @mock.patch("grayprep.cli.verify_full_dataset")
    def test_verify_full_passes_publish_and_source_sample(self, verify: mock.Mock) -> None:
        verify.return_value = {"status": "PASS"}
        result = main(
            [
                "dataset", "verify-full",
                "--output", "/output",
                "--net-config", "/net.yaml",
                "--source", "/source",
                "--source-sample", "1000",
                "--workers", "16",
                "--opencv-threads", "1",
                "--publish",
            ]
        )
        self.assertEqual(result, 0)
        self.assertEqual(verify.call_args.kwargs["source_sample"], 1000)
        self.assertEqual(verify.call_args.kwargs["workers"], 16)
        self.assertTrue(verify.call_args.kwargs["publish"])


if __name__ == "__main__":
    unittest.main()
