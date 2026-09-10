# 单通道训练集成烟测

## 目的

验证 `net1280` 生成的单通道图片能够直接进入 YOLOv8x-Pose-P6 的 1 通道网络，并完成训练、验证和检查点保存。该烟测不评价模型精度。

## 本次运行

- 实验：`20260910_step11_preprocess_smoke21_gray1`
- Ultralytics：`8.3.98`
- 初始化：从 YAML 随机初始化，不加载预训练权重
- 输入：`gray1 [B,1,1280,1280]`
- 模型：YOLOv8x-Pose-P6，`ch=1`、`nc=21`、`kpt_shape=[2,3]`
- 数据：`smoke21-v1`，训练21张、验证21张，每类各1张
- 参数：`epochs=1`、`batch=4`、`workers=4`、`amp=true`
- GPU：物理 GPU 3，通过 UUID 指定；容器内显示为设备 0

## 验收结果

训练和最终验证均正常退出。`results.csv` 有且只有一个 epoch；`best.pt`、`last.pt`、`epoch0.pt` 均已生成。读取 `best.pt` 后确认：

```text
first Conv: in_channels=1, out_channels=80, kernel_size=3x3
model YAML: ch=1, nc=21
pose head: nc=21, kpt_shape=[2,3]
parameter count: 99,192,300
```

模型精度很低是正常现象：这是随机初始化、每类仅一张训练图、只训练一个 epoch 的链路烟测。指标不能用于模型方案比较。

## 产物位置

```text
/data3/ywang/yolo-pose-experiments/20260910_step11_preprocess_smoke21_gray1/
  config.yaml
  dataset.yaml
  command.sh
  logs/train.log
  summary.json
  train/results.csv
  train/args.yaml
  train/weights/best.pt
  train/weights/last.pt
  train/weights/epoch0.pt
```

`best.pt` SHA-256：

```text
0346a5a64cf0b22cdb04db0e859f82028b3d8e5747e9d716cea85aa8cfb6ef3a
```

## 已知事项

- 容器禁网，因此 Ultralytics 的 AMP 参考模型下载检查被跳过；实际 AMP 训练与验证没有出现 NaN 或运行错误。
- 日志显示 Ultralytics 仍构造了默认的低概率 Albumentations 变换。正式精度实验前应明确决定是否保留，并把最终策略写死在配置和测试中。
- 本步没有覆盖 ONNX 导出、量化或 FPGA 权重映射；这些属于训练仓库和量化流水线的后续门禁。
