# yolo-gray1-data-pipeline

目标读者：使用本仓库生成 gray1 训练数据或 FPGA 上板 bin 的人。

本仓库把图像预处理从训练和量化项目中拆出来，保证 YOLO 训练 / 验证 / 测试 / 标定使用同一套几何，并按已确认的相机协议生成上板文件。

- `net1280`：显式读取单通道灰度 → 缩放到 `1000x1000` → 四周补 140 像素 0 → `1280x1280` gray1，并同步变换 YOLO 框和关键点。
- `cam2000`：显式读取单通道灰度 → 缩放到 `2000x2000` → 12-bit packed-u12 → 每行 4096 字节、文件 `8192000` 字节的 `.bin`。

`gray1` 是真正的 1 通道图，不是历史 `R=灰度, G=B=0` 的三通道图。源图语义必须在配置里写明：`native_gray`、`r_only` 或 `color_to_gray`，不要猜测。

固定参数在 [`configs/net1280.yaml`](configs/net1280.yaml) 和 [`configs/cam2000.yaml`](configs/cam2000.yaml)。相机打包细节见 [`docs/CAMERA_BIN_ABI.md`](docs/CAMERA_BIN_ABI.md)。本仓库不包含训练、量化、数据集或模型权重。

## 使用方法

用容器跑，不要在宿主机安装 Python / Conda。镜像默认非 root、无网络、只读根文件系统，也不申请 GPU。

```bash
docker build --pull=false \
  -f docker/Dockerfile \
  -t ywang/yolo-gray1-data-pipeline:0.1.1 .

docker run --rm --network none --read-only \
  ywang/yolo-gray1-data-pipeline:0.1.1
```

Compose 见 [`docker/compose.yaml`](docker/compose.yaml)。典型数据命令：

```bash
# 确定性抽取有界烟测子集
grayprep dataset select-smoke --source /source --output /output/selection.json --seed 20260910

# 生成 net1280 图像/标签和 cam2000 bin
grayprep dataset build-smoke \
  --source /source \
  --manifest /output/selection.json \
  --output /output/smoke21 \
  --net-config /app/configs/net1280.yaml \
  --cam-config /app/configs/cam2000.yaml \
  --schema /app/schemas/preprocess-profile.schema.json

grayprep dataset verify-smoke --output /output/smoke21 --source /source
```

约定：默认不覆盖已有输出；相同输入和配置应得到相同 manifest 与内容哈希；写文件走 `.partial`，校验后再原子改名。源数据只读挂载，派生结果写到调用方提供的输出目录。不要把数据集、`.pt`、`.onnx`、完整 `.bin`、凭据或运行产物提交到 Git。

## 排错

1. **先跑测试和 CI。** 本地：`PYTHONPATH=src python -m pytest -q`。远程：[GitHub Actions](https://github.com/space-exploration-101/yolo-gray1-data-pipeline/actions)。外部 FPGA golden 不在 Git 里，需要时设置 `GRAYPREP_FPGA_GOLDEN_BIN`。
2. **图像通道不对。** 模型输入应是 `[N,1,1280,1280]`。若仍是 3 通道，检查源语义是不是被当成普通 BGR。
3. **bin 大小或解码失败。** 文件必须恰好 `8192000` 字节，每行后 `1096` 字节为 0。对照 [`docs/CAMERA_BIN_ABI.md`](docs/CAMERA_BIN_ABI.md) 检查打包，不要猜字节序。
4. **标签坐标错位。** `net1280` 先按比例缩到 1000，再平移 +140；不可见关键点保持 `[0,0,0]`。
5. **二次运行结果不一致。** 确认配置、种子、源文件哈希未变，且没有手动改过输出目录。
6. **Git 内容门禁失败。** `python scripts/check_git_contents.py` 会拒绝模型、bin、数据集和大于 1 MiB 的文件。
7. **镜像或仓库丢了。** 先看 GitHub；都不可用时按 [docs/RESTORE.md](docs/RESTORE.md) 从 NAS 恢复。

过程性验收记录见 [提交历史](https://github.com/space-exploration-101/yolo-gray1-data-pipeline/commits/main) 和 [Actions](https://github.com/space-exploration-101/yolo-gray1-data-pipeline/actions)。
