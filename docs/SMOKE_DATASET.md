# 21类有界烟测数据说明

目标读者：Human 与 Agent
状态：Step 9 构建完成，Step 10 验证通过。

## 数据来源与边界

源数据只读访问：

```text
/data2/ai-i-chenshiwen/auto_landmark/Dataset/yolo_full
```

源集约824 GB，本次没有复制全量数据。源 YAML 明确 `r_channel_only: true`，抽样检查确认地标图片为 `4096x4096x3`、moon 为 `2048x2048x3`，B/G 通道为0。因此本次烟测显式使用 `r_only` 读取 R 通道；这与未来 PC 彩色仿真 PNG 默认使用 `color_to_gray` 是两种受支持的源语义。

## 选择规则

```text
dataset_id: yolo_full
seed: 20260910
每类每用途: 1
类别数: 21
train: 21
val: 21
test: 21
calibration: 21（从 train 候选中另选，与 train 不重复）
合计: 84
```

候选按 `SHA256(seed|source_split|relative_label)` 排序后选择。相同源集、固定种子和相同代码会得到逐字节相同的 selection manifest。

## 产物

```text
/data3/ywang/yolo-gray1-data-pipeline-validation/step9/smoke21-v1
```

主要内容：

```text
images/{train,val,test,calibration}    84张 1280x1280 gray1 PNG
labels/{train,val,test,calibration}    84个转换后 YOLO-Pose 标签
fpga/test                              21个 2000x2000 packed-u12 bin
selection_manifest.json
manifest.json
dataset.yaml
profiles.resolved.yaml
class_statistics.json
transform_report.json
SHA256SUMS
VERIFIED
```

数据目录总计约 `220,446,949` bytes，共197个文件。每个 FPGA bin 严格为 `8,192,000` bytes。

## Step 10 验收结果

- 195个受管文件 SHA-256 全部通过。
- 84张输出图片全部是 `1280x1280 uint8` 单通道。
- 84张图片四周140像素 padding 全部为0。
- 84个标签全部为11列 YOLO-Pose；坐标按独立公式复算，误差检查通过。
- 四个用途均完整覆盖21类，每类恰好1张。
- split 间无源 stem 重复，无源图内容 SHA-256 重复。
- 84张源图的记录哈希和 R-only 语义重新验证通过。
- 21个 FPGA bin 的大小、padding、严格解码和逐字节重编码全部通过。
- 固定种子重新选择得到与 Step 9 逐字节相同的 manifest。
- 人工查看 class 0 地标及 class 20 moon overlay，框和关键点位置正常。

该数据只用于流水线烟测，不用于评估模型精度。
