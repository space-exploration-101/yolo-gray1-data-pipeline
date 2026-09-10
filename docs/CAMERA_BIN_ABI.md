# `cam2000` 相机 BIN 协议

目标读者：Human 与 Agent
状态：软件协议已确认；Step 7 已使用上板验证过的 `2_1.bin` 完成二进制 ABI 互认。

## 1. 图像处理

默认输入是 PC 仿真生成的 PNG。OpenCV 按 BGR 读取三通道图片并执行：

```text
BGR -> cv2.COLOR_BGR2GRAY
-> cv2.INTER_LINEAR resize 到 2000x2000
-> uint8 0..255 满量程映射到 uint12 0..4095
```

映射公式为：

```text
u12 = round(u8 * 4095 / 255)
```

原生单通道 PNG 可以显式选择 `native_gray`；历史 R-only 图片必须显式选择 `r_only`。不得自动猜测三通道图片的语义。

## 2. 两像素三字节布局

相邻两个像素记为 `P0[11:0]`、`P1[11:0]`：

```text
Byte0      = P0[7:0]
Byte1[3:0] = P0[11:8]
Byte1[7:4] = P1[3:0]
Byte2      = P1[11:4]
```

已知向量：

```text
P0=0xABC, P1=0x123 -> BC 3A 12
P0=0x000, P1=0xFFF -> 00 F0 FF
P0=0xFFF, P1=0x000 -> FF 0F 00
```

该布局是自定义 nibble packing，文档和代码中不以笼统的“大端/小端”替代上述精确位定义。

## 3. 帧布局

```text
宽度                  2000 pixels
高度                  2000 rows
每行有效数据          2000 / 2 * 3 = 3000 bytes
每行固定跨度          4096 bytes
每行尾部零填充        1096 bytes
有效数据总量          6,000,000 bytes
填充总量              2,192,000 bytes
文件总大小            8,192,000 bytes
文件头/文件尾         0 / 0 bytes
```

解码默认执行严格校验：文件大小必须准确，且每行 `[3000:4096]` 全部为零。

## 4. 浮点坐标

质心、BBox 和关键点是连续浮点坐标，预处理过程中不得取整。源图尺寸为 `W x H` 时：

```text
x_cam = x_source * 2000.0 / W
y_cam = y_source * 2000.0 / H
```

例如 `2048x2048` 源图上的 `(560.5, 738.25)` 变换为：

```text
(547.36328125, 720.947265625)
```

报告或 manifest 应区分 `source`、`cam2000` 和后续 `net1280` 坐标空间。

## 5. 发布和验证

- 写文件使用同目录 `.partial`，内存解码回环成功后原子发布。
- Python 自身的 encode/decode 回环只能证明内部一致。
- Step 7 使用上板验证过的 `2_1.bin`，在 H200 验证区重命名为 `fpga-validated-frame-001.bin`。
- 文件 SHA-256 为 `06529cbe42b27710fd6bdf9814d90520aa9f63c8bfe46edf08ba6847eadd2182`。
- 严格解码、全部零填充检查以及解码后重新编码逐字节比较均通过。
- 因为没有同时提供对应的源 PNG，本 golden 已确认 packed-u12 帧 ABI，但没有独立覆盖 `BGR2GRAY`、resize 和 `uint8 -> uint12` 三项图像预处理语义。
