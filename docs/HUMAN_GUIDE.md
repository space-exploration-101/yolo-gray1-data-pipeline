# 人工操作说明

本仓库包含两条数据预处理流水线：

- `net1280`：生成训练、验证、测试和标定使用的 `1280x1280` 单通道数据，并同步转换 YOLO 检测框和关键点。
- `cam2000`：生成 FPGA 上板测试使用的 `2000x2000` 相机协议 bin。

当前已经完成两条流水线的核心库、合成测试和 FPGA 上板验证 bin 的二进制协议互认。批量 manifest/CLI 和真实烟测数据仍在后续步骤完成。

## 人工需要确认的事项

`cam2000` 已确认的软件协议为：

1. 三通道 PNG 使用 OpenCV `BGR2GRAY`，然后以 `INTER_LINEAR` resize 到 `2000x2000`。
2. `uint8` 使用 `round(v * 4095 / 255)` 满量程映射到 12 bit。
3. 两个 12-bit 像素依次打包为三个字节：`P0[7:0]`、`P1[3:0]|P0[11:8]`、`P1[11:4]`。
4. 每行有效 3000 bytes，固定 stride 为 4096 bytes，剩余 1096 bytes 全部填 0。
5. 共 2000 行，无文件头和文件尾，文件大小严格为 8,192,000 bytes。
6. 浮点质心从源图到相机图按连续坐标比例缩放，全程不取整。

Step 7 已使用上板验证过的 `2_1.bin` 完成二进制协议互认。完整 bin 以 `fpga-validated-frame-001.bin` 保存在 H200 的 ywang 验证区，Git 只保存哈希和外部 golden 测试。由于没有对应源 PNG，这次验证覆盖帧大小、打包、行填充和解码/重编码，不独立覆盖 PNG 灰度转换及 resize。

## 容器环境

Step 8 已生成 `ywang/yolo-gray1-data-pipeline:0.1.0-dev`。镜像固定 Python 基础镜像 digest 和全部 Python 依赖哈希，不依赖宿主机 Python/Conda，不使用 GPU。默认以非 root 用户、无网络和只读根文件系统运行。构建及验收命令见 `docs/CONTAINER.md`。

## 21类烟测数据

Step 9–10 已从只读 `yolo_full` 中按固定种子选择并验证84张样本，train/val/test/calibration 各21张、每类1张；test 额外生成21个 FPGA bin。烟测数据只用于验证流水线，不用于判断模型精度，详见 `docs/SMOKE_DATASET.md`。

## 训练集成烟测

Step 11 已使用上述烟测集完成一轮从头初始化的 YOLOv8x-Pose-P6 单通道训练：输入为 `[B,1,1280,1280]`，21 类、每目标 2 个关键点，训练和验证各使用21张图片，运行 1 epoch。训练成功生成 `best.pt`、`last.pt` 和结果日志；检查点首层确认是 1 输入通道，模型配置确认是 `ch=1、nc=21、kpt_shape=[2,3]`。

这一步只证明“预处理输出可以被单通道训练链路正确读取，并能完成反向传播、验证和权重保存”，不用于判断精度。详细记录见 `docs/TRAINING_INTEGRATION.md`。

## 安全边界

- 不修改 chenshiwen 或 root 的文件。
- 不在主机安装 Python、Conda 或依赖。
- 不将真实数据、模型、凭据或大规模 bin 提交到 Git。
- 未经授权不处理全量数据、不使用 GPU、不写 NAS。

详细进度见 `docs/PROGRESS.md`。

## Git 发布说明

Step 12 已完成提交前内容审查：源码、配置、Schema、测试和文档可以进入 Git；数据集、模型、ONNX、FPGA 完整 bin、日志、训练输出和凭据均由忽略规则排除。Python 包开发版本已统一为 `0.1.0.dev0`，并通过离线 wheel 构建与安装测试。

仓库中的进度和来源文档包含 H200 内部绝对路径、用户名、来源哈希和一个 GPU UUID。它们不是密码，但不适合无审查地公开发布。因此首次创建 GitHub 仓库时建议选择 `private`；如果必须公开，应先删减或匿名化这些运行记录。
