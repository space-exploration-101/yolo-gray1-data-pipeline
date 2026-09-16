"""Command-line skeleton for the preprocessing repository."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json

from grayprep import __version__
from grayprep.dataset_full import (
    build_full_dataset,
    create_medium_manifest,
    create_full_manifest,
    verify_full_dataset,
    write_full_manifest,
)
from grayprep.dataset_smoke import (
    build_smoke_dataset,
    create_smoke_manifest,
    verify_smoke_dataset,
    write_selection_manifest,
)


PIPELINES = {
    "net1280": "训练、验证、测试和标定数据：1000x1000 后四周 padding 到 1280x1280",
    "cam2000": "FPGA 上板输入：2000x2000 的 12-bit 相机协议 bin",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grayprep", description="YOLO gray1 数据预处理")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="列出可用的预处理流水线")

    run_parser = subparsers.add_parser("run", help="运行一条预处理流水线（尚未实现）")
    run_parser.add_argument("pipeline", choices=sorted(PIPELINES))
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--manifest", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--dry-run", action="store_true")

    dataset_parser = subparsers.add_parser("dataset", help="数据集索引、构建和验证工具")
    dataset_commands = dataset_parser.add_subparsers(dest="dataset_command", required=True)
    select_parser = dataset_commands.add_parser("select-smoke", help="确定性选择每类烟测样本")
    select_parser.add_argument("--source", required=True)
    select_parser.add_argument("--output", required=True)
    select_parser.add_argument("--seed", type=int, required=True)
    select_parser.add_argument("--per-class", type=int, default=1)
    build_parser_smoke = dataset_commands.add_parser("build-smoke", help="生成 net1280 和 cam2000 烟测产物")
    build_parser_smoke.add_argument("--source", required=True)
    build_parser_smoke.add_argument("--manifest", required=True)
    build_parser_smoke.add_argument("--output", required=True)
    build_parser_smoke.add_argument("--net-config", required=True)
    build_parser_smoke.add_argument("--cam-config", required=True)
    build_parser_smoke.add_argument("--schema", required=True)
    build_parser_smoke.add_argument("--workers", type=int, default=1)
    build_parser_smoke.add_argument("--opencv-threads", type=int)
    verify_parser = dataset_commands.add_parser("verify-smoke", help="严格验证烟测产物")
    verify_parser.add_argument("--output", required=True)
    verify_parser.add_argument("--source")
    index_full_parser = dataset_commands.add_parser("index-full", help="生成确定性的全量源数据索引")
    index_full_parser.add_argument("--source", required=True)
    index_full_parser.add_argument("--output", required=True)
    index_full_parser.add_argument("--schema", required=True)
    select_medium_parser = dataset_commands.add_parser("select-medium", help="从全量索引生成固定 M 规模清单")
    select_medium_parser.add_argument("--manifest", required=True)
    select_medium_parser.add_argument("--output", required=True)
    select_medium_parser.add_argument("--schema", required=True)
    select_medium_parser.add_argument("--seed", required=True)
    select_medium_parser.add_argument("--views-per-group", type=int, default=10)
    select_medium_parser.add_argument("--empty-per-group", type=int, default=2)
    select_medium_parser.add_argument("--moon-train", type=int, default=600)
    build_full_parser = dataset_commands.add_parser("build-full", help="断点续跑构建全量 net1280 数据")
    build_full_parser.add_argument("--source", required=True)
    build_full_parser.add_argument("--manifest", required=True)
    build_full_parser.add_argument("--output", required=True)
    build_full_parser.add_argument("--net-config", required=True)
    build_full_parser.add_argument("--profile-schema", required=True)
    build_full_parser.add_argument("--manifest-schema", required=True)
    build_full_parser.add_argument("--workers", type=int, default=1)
    build_full_parser.add_argument("--opencv-threads", type=int)
    build_full_parser.add_argument("--resume", action="store_true")
    verify_full_parser = dataset_commands.add_parser("verify-full", help="验证并可原子发布全量数据")
    verify_full_parser.add_argument("--output", required=True)
    verify_full_parser.add_argument("--net-config", required=True)
    verify_full_parser.add_argument("--source")
    verify_full_parser.add_argument("--source-sample", type=int, default=0)
    verify_full_parser.add_argument("--workers", type=int, default=1)
    verify_full_parser.add_argument("--opencv-threads", type=int)
    verify_full_parser.add_argument("--publish", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        for name, description in PIPELINES.items():
            print(f"{name}: {description}")
        return 0
    if args.command == "dataset" and args.dataset_command == "select-smoke":
        manifest = create_smoke_manifest(args.source, seed=args.seed, per_class=args.per_class)
        write_selection_manifest(args.output, manifest)
        print(json.dumps({"status": "PASS", "items": manifest["item_count"], "output": args.output}, ensure_ascii=False))
        return 0
    if args.command == "dataset" and args.dataset_command == "build-smoke":
        output = build_smoke_dataset(
            args.source,
            args.manifest,
            args.output,
            net_profile_path=args.net_config,
            cam_profile_path=args.cam_config,
            schema_path=args.schema,
            workers=args.workers,
            opencv_threads=args.opencv_threads,
        )
        print(json.dumps({"status": "PASS", "output": str(output)}, ensure_ascii=False))
        return 0
    if args.command == "dataset" and args.dataset_command == "verify-smoke":
        print(json.dumps(verify_smoke_dataset(args.output, source_root=args.source), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "dataset" and args.dataset_command == "index-full":
        manifest = create_full_manifest(args.source, schema_path=args.schema)
        write_full_manifest(args.output, manifest)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "items": manifest["item_count"],
                    "source_revision": manifest["source_revision"],
                    "output": args.output,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "dataset" and args.dataset_command == "build-full":
        staging = build_full_dataset(
            args.source,
            args.manifest,
            args.output,
            net_profile_path=args.net_config,
            profile_schema_path=args.profile_schema,
            manifest_schema_path=args.manifest_schema,
            workers=args.workers,
            opencv_threads=args.opencv_threads,
            resume=args.resume,
        )
        print(json.dumps({"status": "BUILT_PENDING_VERIFICATION", "output": str(staging)}, ensure_ascii=False))
        return 0
    if args.command == "dataset" and args.dataset_command == "select-medium":
        manifest = create_medium_manifest(
            args.manifest,
            schema_path=args.schema,
            seed=args.seed,
            views_per_group=args.views_per_group,
            empty_per_group=args.empty_per_group,
            moon_train=args.moon_train,
        )
        write_full_manifest(args.output, manifest)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "items": manifest["item_count"],
                    "split_counts": manifest["split_counts"],
                    "source_revision": manifest["source_revision"],
                    "output": args.output,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "dataset" and args.dataset_command == "verify-full":
        report = verify_full_dataset(
            args.output,
            net_profile_path=args.net_config,
            source_root=args.source,
            source_sample=args.source_sample,
            workers=args.workers,
            opencv_threads=args.opencv_threads,
            publish=args.publish,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    raise SystemExit("run 命令尚未实现；请使用 dataset 下的明确子命令")


if __name__ == "__main__":
    raise SystemExit(main())
