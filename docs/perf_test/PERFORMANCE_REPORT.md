# Grayprep 性能结论

## 最终结论

2026-09-11 在 H200 共享服务器上完成 CPU 端到端验收。推荐配置为：

```text
workers: 32
opencv_threads_per_worker: 1
output_scratch: /data1
fallback: 1 worker x 8 OpenCV threads
GPU: 不需要
```

固定 4,200-item p50 数据集的组合流程从单进程基线 `2.1114 items/s` 提升到
`54.7514 items/s`，吞吐提升 **25.93 倍**，等量 wall time 降低 **96.14%**。
最终三轮吞吐分别为 `52.9785`、`54.7514`、`54.8325 items/s`，波动
**3.39%**，满足不超过 5% 的稳定性门禁。

三轮输出的 SHA-256 清单完全一致。最终校验覆盖 4,200 个 item、9,456 个哈希和
1,050 个 cam2000 BIN，失败数为 0，残留 `.partial` 为 0。`/data1` NVMe scratch
相比 `/data3` 输出路径快约 **10.55%**。

主要瓶颈是 CPU PNG 解码。图片级多进程带来主要收益；cam2000 pack/decode 的整帧
NumPy 向量化也已接受。OpenCV 单进程线程数、uint8 到 uint12 整数/LUT、重复哈希复用、
net1280 内存路径和 PNG 压缩级别均未带来足够的端到端收益。当前没有证据支持迁移 GPU。

## 简要试验步骤

1. 固定输入 manifest、代码版本、镜像、配置和存储路径，记录单进程端到端基线。
2. 运行 unit、golden 和小规模 smoke 测试，保存输出 SHA-256 作为正确性基准。
3. 分阶段测量读取、PNG 解码、resize、padding、uint12 转换、BIN pack/decode、哈希和写盘。
4. 扫描 OpenCV 线程数，确认单进程线程扩展对端到端吞吐影响很小。
5. 将 cam2000 pack/decode 改为整帧 NumPy 切片，并验证 BIN 逐字节一致。
6. 扫描图片级多进程组合，选择 `32 workers x 1 OpenCV thread`。
7. 对 `/data1` 与 `/data3` 做相同配置的存储 A/B，选择 `/data1` 作为 scratch。
8. 使用 4,200-item 数据集正式运行三轮，比较吞吐、波动、资源占用和完整输出哈希。

所有正式性能比较均采用端到端吞吐和三轮中位数；任何改变输出字节、协议校验失败或
残留临时文件的候选都不接受。
