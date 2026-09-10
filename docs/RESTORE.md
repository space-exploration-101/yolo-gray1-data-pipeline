# 从 NAS 恢复

目标读者：H200 崩溃、仓库丢失或 Docker 镜像被误删时，需要把预处理环境找回来的人。

GitHub 是源码远程。下面这份 NAS 备份是灾难恢复副本，不和 GitHub 自动同步。

## 备份位置

```text
\\10.2.26.26\902_data\0-项目\13-专项\4-代码\训练平台\yolo-gray1-data-pipeline\v0.1.1
```

H200 挂载 NAS 后：

```text
/mnt/ywang-nas/0-项目/13-专项/4-代码/训练平台/yolo-gray1-data-pipeline/v0.1.1
```

当前备份对应 tag `v0.1.1`，commit `5787aa904ff80a71d585a527bc4ad973c288e48a`。目录内必须有 `VERIFIED`，且没有 `.partial`。

同级还有训练环境备份 `ywang-yolo-gray1-env-20260909_124030/`，那是 YOLO 训练镜像，不是本仓库。总说明见 NAS 上的 `备份说明.md`。

## 备份里有什么

| 文件 | 用途 |
|---|---|
| `source-v0.1.1.tar.zst` | 该 tag 的源码树 |
| `yolo-gray1-data-pipeline.bundle` | 含历史和 tag 的 Git 镜像 |
| `image-0.1.1.tar.zst` | `ywang/yolo-gray1-data-pipeline:0.1.1` |
| `smoke21-v1.tar.zst` | 21 类有界烟测（seed `20260910`） |
| `fpga-validated-frame-001.bin` | 上板验证过的 cam2000 golden |

不含 824G 原始 `yolo_full`，不含凭据。

## 什么时候用

- Docker 里找不到 `ywang/yolo-gray1-data-pipeline:0.1.1`。
- `/data3/ywang/yolo-gray1-data-pipeline` 丢失，GitHub 也暂时不可用。
- 需要把 FPGA golden 或烟测样本拿回来做协议核对。

若 GitHub 仍在，优先 `git clone` 后重新 `docker build`。NAS 用于 GitHub 或本地镜像都不可用时。

## 怎么恢复

先校验：

```bash
cd /mnt/ywang-nas/0-项目/13-专项/4-代码/训练平台/yolo-gray1-data-pipeline/v0.1.1
sha256sum -c SHA256SUMS
zstd -q -t image-0.1.1.tar.zst source-v0.1.1.tar.zst smoke21-v1.tar.zst
```

装镜像：

```bash
zstd -dc image-0.1.1.tar.zst | docker load
docker image inspect ywang/yolo-gray1-data-pipeline:0.1.1
```

恢复仓库到新的空目录，不要覆盖正在用的目录：

```bash
git clone yolo-gray1-data-pipeline.bundle /data3/ywang/yolo-gray1-data-pipeline-restored
```

## 什么时候可以不再用这份备份

GitHub 发布了更新的 tag（例如 `v0.1.2`），并且 NAS 上已经有该版本的 `VERIFIED` 备份之后，`v0.1.1` 可以停用。新备份校验失败时，继续保留这一份。