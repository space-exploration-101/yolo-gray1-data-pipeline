# 容器构建与验证

目标读者：Human 与 Agent

## 固定环境

基础镜像固定为：

```text
python:3.12-slim
digest: sha256:804ddf3251a60bbf9c92e73b7566c40428d54d0e79d3428194edf40da6521286
Python: 3.12.13
```

主要包：

```text
numpy==1.26.4
opencv-python-headless==4.11.0.86
PyYAML==6.0.3
jsonschema==4.25.1
pytest==8.4.2
```

直接和传递依赖全部在 `docker/requirements.lock.txt` 中固定版本和 wheel SHA-256。构建使用 `pip --require-hashes`，下载内容与锁文件不匹配时立即失败。

## 构建

H200 当前没有 buildx，Step 8 使用 Docker 经典构建器，不需要修改 Docker 全局配置：

```bash
cd /data3/ywang/yolo-gray1-data-pipeline
docker build --pull=false \
  --build-arg VCS_REF=uncommitted-step8 \
  -f docker/Dockerfile \
  -t ywang/yolo-gray1-data-pipeline:0.1.0-dev .
```

当前开发镜像：

```text
image: ywang/yolo-gray1-data-pipeline:0.1.0-dev
image_id: sha256:a5467801702937e65521e776628d4860834cc9748cd43d3a5bde349ae3c48402
size: 354869139 bytes
revision: uncommitted-step9
```

正式发布前应使用实际 Git commit 替代 `uncommitted-step8`，重新构建并记录新的镜像 ID。

## 安全运行约束

- 默认镜像用户是 `65532:65532`，不是 root。
- H200 Compose 使用 `1012:1012`，确保派生文件属于 ywang。
- `network_mode: none`。
- 根文件系统只读，仅 `/tmp` 使用有界 tmpfs。
- 输入目录只读，输出目录单独读写。
- 不声明或使用 GPU。
- `.dockerignore` 排除数据、模型、bin、测试报告和 Git 历史。

## 验证

Step 8 已执行：

```text
Compose config                       PASS
严格哈希依赖安装                    PASS
镜像内 Draft 2020-12 Schema         PASS
net1280.yaml                         PASS
cam2000.yaml                         PASS
pip check                            PASS
完整测试（含外部 FPGA golden）      44 passed
```

FPGA 完整 golden bin 不进入镜像或 Git，需要验证时通过只读挂载和 `GRAYPREP_FPGA_GOLDEN_BIN` 指定。
