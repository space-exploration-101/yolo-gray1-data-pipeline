# Git 发布前内容审查

## 审查结论

Step 12 已通过。仓库候选内容仅包含源码、配置、JSON Schema、容器定义、测试、小型文本 golden fixture 和文档。没有发现凭据、密钥、访问令牌、模型权重、ONNX、完整 FPGA bin、训练数据、运行日志、软链接、非 UTF-8 文件或超过 1 MB 的文件。

Step 13 开始发布：目标为组织 `space-exploration-101` 下的私有仓库 `yolo-gray1-data-pipeline`。首次 commit 只包含 Step 12 审查过的候选文件以及 GitHub Actions CI。

## Git 应包含的内容

- `src/grayprep/`：两条预处理流水线与批量烟测数据构建逻辑。
- `configs/`、`schemas/`：固定预处理协议及 manifest 约束。
- `docker/`：哈希锁定的运行环境。
- `tests/`：单元测试和小型文本/PGM golden fixture。
- `docs/`、`README.md`：中文人工说明、Agent 记录和协议文档。

Python 包开发版本统一为 `0.1.0.dev0`；容器开发标签仍为 `0.1.0-dev`。项目声明为 `LicenseRef-Proprietary`。

## Git 必须排除的内容

`.gitignore` 已验证会排除：

- `.env`、凭据、私钥；
- 数据集、派生数据、cache、runs 和 outputs；
- `.pt`、`.onnx`、`.engine`、`.bin`；
- 压缩包、日志和临时 `.partial` 文件。

完整 FPGA golden bin、21类烟测数据、Step 11 训练权重和所有验证报告继续保存在 H200 的 ywang 外部验证/实验目录，后续由 NAS 备份步骤处理，不进入 Git。

## 验证结果

- Git 候选内容审查：0 个阻断项。
- 当前工作树测试：46 项通过；测试时明确使用 `/workspace/src`，没有误用镜像内旧源码。
- wheel：离线构建成功，安装到临时目录后 `grayprep --version` 和流水线列表检查通过。
- ignore probes：模型、ONNX、bin、日志、凭据、环境文件、数据和输出目录均正确命中忽略规则。

## GitHub 发布门禁

目标组织为 `space-exploration-101`，建议仓库名为 `yolo-gray1-data-pipeline`。

仓库运行记录包含内部绝对路径、用户名、来源哈希和一个 GPU UUID；这些不是访问凭据，但具有内部环境信息。首次发布建议创建 private 仓库。如果需要 public，应先执行一次专门的文档匿名化审查。

创建组织仓库、写入 Deploy Key 和启用 Actions 属于账号所有者操作。Agent 在获得授权后创建首次 commit、配置 `origin` 并 push，然后核对该 commit 上的 CI。
