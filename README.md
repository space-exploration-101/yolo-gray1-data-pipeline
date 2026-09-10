# yolo-gray1-data-pipeline

本仓库用于独立、可复现地生成 YOLO 原生单通道灰度数据，以及符合相机协议的 FPGA 上板测试输入。

包含两条流水线：

- `net1280`：图像缩放到 `1000x1000`，四周补 140 像素，并同步转换 YOLO 检测框和关键点，最终生成 `1280x1280` gray1 数据。
- `cam2000`：图像缩放到 `2000x2000`，按照确认后的 12-bit 相机协议编码为二进制文件。

当前状态：`net1280`、`cam2000` 核心库、FPGA golden bin、锁定依赖容器、21类有界烟测数据和单通道训练集成烟测已经完成。Step 12 已完成 Git 内容审查。目标私有仓库为 `https://github.com/space-exploration-101/yolo-gray1-data-pipeline`。CI 在 push/`main` 与 pull request 上运行内容门禁、锁定依赖测试和容器构建。烟测结果见 `docs/SMOKE_DATASET.md` 和 `docs/TRAINING_INTEGRATION.md`。

## 容器

构建不依赖 buildx，可使用 H200 当前 Docker 经典构建器：

```bash
docker build --pull=false \
  -f docker/Dockerfile \
  -t ywang/yolo-gray1-data-pipeline:0.1.0-dev .
```

查看当前流水线：

```bash
docker run --rm --network none --read-only \
  ywang/yolo-gray1-data-pipeline:0.1.0-dev
```

镜像默认以非 root 的 `65532:65532` 运行；H200 Compose 显式覆盖为 ywang 的 `1012:1012`。镜像不申请 GPU，默认禁用网络并使用只读根文件系统。依赖版本及哈希见 `docker/requirements.lock.txt`。

操作边界：

- 不修改 chenshiwen 或 root 所有的文件。
- 不向 Git 提交数据集、模型、ONNX、大规模 bin、凭据或运行输出。
- 运行依赖使用容器，不在 H200 主机直接安装 Python 或 Conda。
- 源数据通过只读路径访问，派生数据只写入 ywang 所有的目录。

GitHub 远程：`https://github.com/space-exploration-101/yolo-gray1-data-pipeline`。当前仓库为 public。Git 不包含数据集、模型、完整 FPGA bin 或验证输出。
