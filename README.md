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
  -t ywang/yolo-gray1-data-pipeline:0.2.1 .

docker run --rm --network none --read-only \
  ywang/yolo-gray1-data-pipeline:0.2.1
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
  --schema /app/schemas/preprocess-profile.schema.json \
  --workers 32 \
  --opencv-threads 1

grayprep dataset verify-smoke --output /output/smoke21 --source /source
```

### 全量训练数据

全量流程分成索引、可续跑构建和严格验证三个门禁。`build-full` 只写
`<output>.partial`；只有 `verify-full --publish` 全部通过后才原子发布正式目录。

```bash
# 1. 冻结完整源数据清单；不解码图片，也不写源目录
grayprep dataset index-full \
  --source /source \
  --output /output/yolo-full-index.json \
  --schema /app/schemas/full-dataset-manifest.schema.json

# 可选：生成 M 规模训练清单；val/test 保持完整
grayprep dataset select-medium \
  --manifest /output/yolo-full-index.json \
  --output /output/yolo-medium-index.json \
  --schema /app/schemas/full-dataset-manifest.schema.json \
  --seed 20260917-medium-v1 \
  --views-per-group 10 \
  --empty-per-group 2 \
  --moon-train 600

# 2. 只生成 net1280 Gray1 图像和标签；中断后使用相同命令加 --resume
grayprep dataset build-full \
  --source /source \
  --manifest /output/yolo-medium-index.json \
  --output /output/pose21-gray1-1280-m-v1 \
  --net-config /app/configs/net1280.yaml \
  --profile-schema /app/schemas/preprocess-profile.schema.json \
  --manifest-schema /app/schemas/full-dataset-manifest.schema.json \
  --workers 32 \
  --opencv-threads 1

# 3. 校验全部派生文件，确定性抽检 1000 个源图变换，然后原子发布
grayprep dataset verify-full \
  --output /output/pose21-gray1-1280-m-v1 \
  --net-config /app/configs/net1280.yaml \
  --source /source \
  --source-sample 1000 \
  --workers 32 \
  --opencv-threads 1 \
  --publish
```

`--source-sample 0` 表示逐项复算全部源图、R-only 语义、Gray1 像素和标签变换；正整数表示按源相对路径 SHA-256 排序后进行确定性抽检。正式 `--publish` 必须同时提供 `--source`。发布目录包含 `manifest.json`、`SHA256SUMS`、`verification_report.json` 和 `VERIFIED`。全量流程保留原 train/val/test、空标签和 `group_id`，不会生成 `cam2000` BIN。

M 规模规则固定为：20 个地标使用全部训练 group，每组最多 10 个视角，目标为 2 个空标签加 8 个正样本；不足 2 个空标签时用正样本补足。`moon` 按 seed 确定性选择 600 张。val/test 完整保留，保证不同训练规模共享同一评估基准。

断点续跑只接受相同源文件元数据、源标签哈希、源 manifest 和 net1280 配置。恢复时逐项校验已经完成的输出；不一致的单项派生文件会在暂存目录内重建，不会修改源数据。正式目录已存在时，构建和发布都会拒绝覆盖。

约定：默认不覆盖已有输出；相同输入和配置应得到相同 manifest 与内容哈希；写文件走 `.partial`，校验后再原子改名。源数据只读挂载，派生结果写到调用方提供的输出目录。不要把数据集、`.pt`、`.onnx`、完整 `.bin`、凭据或运行产物提交到 Git。

`build-smoke`、`build-full` 和 `verify-full` 默认 `--workers 1`，用于兼容和问题回退。批量处理的已验证配置是
`--workers 32 --opencv-threads 1`；多进程模式必须显式给出 `--opencv-threads`，避免
每个进程各自创建过多 OpenCV 线程。H200 是共享服务器，实际 worker 数仍需服从当时
的 CPU、内存和存储负载。

## 性能验收

2026-09-11 在 H200 上使用固定的 4,200-item p50 数据集完成 CPU 端到端验收。组合流程
从单进程基线的 `2.1114 items/s` 提升到 `32 workers x 1 OpenCV thread` 的
`54.7514 items/s`，吞吐提升 **25.93 倍**，等量 wall time 降低 **96.14%**。最终三轮
吞吐为 `52.9785 / 54.7514 / 54.8325 items/s`，波动 **3.39%**。

三轮输出的 SHA-256 清单完全一致；共检查 4,200 个 item、9,456 个哈希和 1,050 个
cam2000 BIN，失败数和残留 `.partial` 均为 0。`/data1` NVMe scratch 相比 `/data3`
输出路径快约 **10.55%**，因此批处理推荐使用 `/data1` 作为临时输出盘。当前热点主要是
CPU PNG 解码，现有证据不支持为该流程引入 GPU。

性能结论和简要试验步骤见
[`docs/perf_test/PERFORMANCE_REPORT.md`](docs/perf_test/PERFORMANCE_REPORT.md)。

## 排错

1. **先跑测试和 CI。** 本地：`PYTHONPATH=src python -m pytest -q`。远程：[GitHub Actions](https://github.com/space-exploration-101/yolo-gray1-data-pipeline/actions)。外部 FPGA golden 不在 Git 里，需要时设置 `GRAYPREP_FPGA_GOLDEN_BIN`。
2. **图像通道不对。** 模型输入应是 `[N,1,1280,1280]`。若仍是 3 通道，检查源语义是不是被当成普通 BGR。
3. **bin 大小或解码失败。** 文件必须恰好 `8192000` 字节，每行后 `1096` 字节为 0。对照 [`docs/CAMERA_BIN_ABI.md`](docs/CAMERA_BIN_ABI.md) 检查打包，不要猜字节序。
4. **标签坐标错位。** `net1280` 先按比例缩到 1000，再平移 +140；不可见关键点保持 `[0,0,0]`。
5. **二次运行结果不一致。** 确认配置、种子、源文件哈希未变，且没有手动改过输出目录。
6. **Git 内容门禁失败。** `python scripts/check_git_contents.py` 会拒绝模型、bin、数据集和大于 1 MiB 的文件。
7. **镜像或仓库丢了。** 先看 GitHub；都不可用时按 [docs/RESTORE.md](docs/RESTORE.md) 从 NAS 恢复。
8. **全量构建中断。** 保留 `<output>.partial`，确认源 manifest 和配置未变化后，对原命令增加 `--resume`。不要手工移动半成品或伪造 `VERIFIED`。
9. **全量发布失败。** 查看 `verify-full` 的首批 failure；修复工具后从暂存目录续跑或重新验证。只有 `--publish` 成功才会出现正式目录。

过程性验收记录见 [提交历史](https://github.com/space-exploration-101/yolo-gray1-data-pipeline/commits/main) 和 [Actions](https://github.com/space-exploration-101/yolo-gray1-data-pipeline/actions)。
