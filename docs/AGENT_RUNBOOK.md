# Agent Runbook

Human-facing documents are Chinese by default. Stable configuration fields, schemas, code identifiers, and Agent-only records may use English.

Hard boundaries:

- Work only under ywang-owned paths.
- Treat chenshiwen data and source as read-only.
- Do not modify root configuration or install host Python/Conda dependencies.
- Pause after every step and update `docs/PROGRESS.md` only after verification passes.
- `cam2000` 的软件 ABI 已在 Step 6 固化，Step 7 已用上板验证 bin 完成 packed-u12 帧 ABI 互认。
- Do not configure a Git remote or push without explicit authorization at the publication gate.

Steps 9–10 built and verified the bounded `smoke21-v1` dataset: one item per class in train/val/test/calibration plus 21 FPGA bins. Step 11 completed the separately authorized one-epoch YOLOv8x-Pose-P6 gray1 integration smoke and verified a one-channel checkpoint. Step 12 reviewed the complete Git candidate set, fixed release metadata, and verified tests plus an offline wheel install. Step 13 is the GitHub publication gate: first commit, private repository `space-exploration-101/yolo-gray1-data-pipeline`, push, and CI verification. Default visibility is private because operational documents contain internal paths and provenance details. Do not continue to Step 14 until CI on the published `main` commit has passed.
