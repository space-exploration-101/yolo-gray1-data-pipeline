# Agent Runbook

Human-facing documents are Chinese by default. Stable configuration fields, schemas, code identifiers, and Agent-only records may use English.

Hard boundaries:

- Work only under ywang-owned paths.
- Treat chenshiwen data and source as read-only.
- Do not modify root configuration or install host Python/Conda dependencies.
- Pause after every step and update `docs/PROGRESS.md` only after verification passes.
- `cam2000` 的软件 ABI 已在 Step 6 固化，Step 7 已用上板验证 bin 完成 packed-u12 帧 ABI 互认。
- Do not configure a Git remote or push without explicit authorization at the publication gate.

Steps 9–10 built and verified the bounded `smoke21-v1` dataset: one item per class in train/val/test/calibration plus 21 FPGA bins. Step 11 completed the separately authorized one-epoch YOLOv8x-Pose-P6 gray1 integration smoke and verified a one-channel checkpoint. Step 12 reviewed the complete Git candidate set, fixed release metadata, and verified tests plus an offline wheel install. Step 14 cloned `a8709e5` from GitHub into a disposable ywang directory, rebuilt `ywang/yolo-gray1-data-pipeline:0.1.0-step14` with that commit as `VCS_REF`, passed 46 tests including the external FPGA golden, and reproduced the Step 9 smoke hashes. Pause before Step 15 `v0.1.0` tagging.
