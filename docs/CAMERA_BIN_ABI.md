# `cam2000` 相机 BIN 协议

目标读者：实现或核对 FPGA 上板 bin 的人。

## 图像

三通道 PNG 按 OpenCV BGR 读取后：

```text
BGR2GRAY -> INTER_LINEAR resize 到 2000x2000 -> u12 = round(u8 * 4095 / 255)
```

单通道图用 `native_gray`，历史 R-only 图用 `r_only`。不要自动猜测三通道语义。

## 打包

两个 12-bit 像素 `P0`、`P1` 写成三个字节：

```text
Byte0      = P0[7:0]
Byte1[3:0] = P0[11:8]
Byte1[7:4] = P1[3:0]
Byte2      = P1[11:4]
```

例子：`P0=0xABC, P1=0x123` → `BC 3A 12`。

## 帧

```text
2000 x 2000, 每行有效 3000 bytes, stride 4096, 行尾 1096 bytes 填 0
无文件头/尾, 文件大小 = 8192000 bytes
```

严格解码时大小不对或行尾非零即失败。质心等浮点坐标按 `x * 2000 / W` 连续缩放，过程中不取整。

上板互认向量（Git 只保存哈希）：SHA-256 `06529cbe42b27710fd6bdf9814d90520aa9f63c8bfe46edf08ba6847eadd2182`。