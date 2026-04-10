# 2026-4-9 Raw和Time-Space绘图优化

## 1. 背景

本次修改聚焦于 `pcie7825_gui` 中两类绘图路径：

1. Tab1 的 Raw 时域曲线绘图
2. Tab2 的 Time-Space 二维颜色图绘图

优化目标如下：

- 提升 Tab1 Raw 大点数曲线的显示效率
- 将 Raw 时域图刷新节流调整为 `1.0 s`
- Raw 曲线改为显示原始整数值，不再归一化为电压
- 为 Tab2 启用真正的 `QTimer + pending_update` 合并刷新机制
- 去掉 Tab2 每次更新时的 `np.hstack(...)` 全量拼接，改为固定尺寸滚动显示缓冲区

相关文件：

- [main_window.py](/E:/codes/das_fs_7825/pcie7825_gui/src/main_window.py)
- [config.py](/E:/codes/das_fs_7825/pcie7825_gui/src/config.py)
- [time_space_plot.py](/E:/codes/das_fs_7825/pcie7825_gui/src/time_space_plot.py)

## 2. 修改内容

### 2.1 Tab1 Raw 曲线补充 PyQtGraph 大曲线优化调用

修改位置：

- [main_window.py](/E:/codes/das_fs_7825/pcie7825_gui/src/main_window.py#L814)

修改内容：

- 在 `self.plot_widget_1.plot(...)` 创建出的 `PlotDataItem` 上补充以下调用：
  - `setClipToView(True)`
  - `setDownsampling(auto=True, method="peak")`
  - `setSkipFiniteCheck(True)`

目的：

- `setClipToView(True)`：只处理当前可视区域附近的数据
- `setDownsampling(auto=True, method="peak")`：在缩放时自动抽稀并保留峰值特征
- `setSkipFiniteCheck(True)`：减少每次更新时的有限值检查开销

效果：

- 更适合 `200k` 量级的一维曲线实时刷新
- 与 `FIPread` 中 1D 大曲线的推荐用法保持一致

### 2.2 Raw 时域图刷新节流改为 1.0 s

修改位置：

- [config.py](/E:/codes/das_fs_7825/pcie7825_gui/src/config.py#L242)

修改内容：

- `RAW_DATA_CONFIG['time_domain_update_s']` 由 `3` 调整为 `1.0`

目的：

- 让 Raw 时域图的主窗口绘图节流与目标场景一致，即每秒最多刷新一次

说明：

- 这是 GUI 层的刷新节流
- 采集线程的按需取数间隔 `RAW_SAMPLING_CONFIG['time_domain_interval_s']` 仍保持当前配置不变

### 2.3 Raw 曲线去掉归一化，改为整数显示

修改位置：

- [main_window.py](/E:/codes/das_fs_7825/pcie7825_gui/src/main_window.py#L1575)
- [main_window.py](/E:/codes/das_fs_7825/pcie7825_gui/src/main_window.py#L1628)
- [main_window.py](/E:/codes/das_fs_7825/pcie7825_gui/src/main_window.py#L1657)

修改前：

```python
normalized_frame = averaged_frame.astype(np.float32) / 32767.0
```

修改后思路：

- 使用 `display_frame = averaged_frame.astype(np.int32, copy=False)`
- 曲线直接显示整数原值

同时做了以下配套调整：

- Tab1 Raw 曲线 Y 轴标题由 `Amp. (V)` 改为 `Amp.`
- 双通道 Raw 模式下，第二通道在 `plot_widget_2` 中显示时也改为整数值

目的：

- 保持 Raw 数据显示与设备返回值一致
- 避免用户误解当前曲线已经进行了电压物理量换算

### 2.4 Tab2 启用真正的 QTimer + pending_update 合并刷新

修改位置：

- [time_space_plot.py](/E:/codes/das_fs_7825/pcie7825_gui/src/time_space_plot.py#L83)
- [time_space_plot.py](/E:/codes/das_fs_7825/pcie7825_gui/src/time_space_plot.py#L528)
- [time_space_plot.py](/E:/codes/das_fs_7825/pcie7825_gui/src/time_space_plot.py#L669)

修改内容：

- 为 `self._display_timer` 显式设置周期：`self._display_timer.setInterval(self._update_interval_ms)`
- 在点击 `PLOT` 启用绘图时启动定时器
- 在关闭绘图时停止定时器并清空 `pending_update`
- 在 `update_data()` 中不再直接强制重绘，而是仅置位 `_pending_update = True`
- 定时器回调 `_process_pending_update()` 中统一触发 `_update_display()`

目的：

- 合并短时间内多次到达的数据更新请求
- 避免数据每到一批就立刻重绘，从而减少 GUI 抖动和重绘压力

### 2.5 Tab2 去掉每次 np.hstack(...)，改为固定显示缓冲区

修改位置：

- [time_space_plot.py](/E:/codes/das_fs_7825/pcie7825_gui/src/time_space_plot.py#L608)
- [time_space_plot.py](/E:/codes/das_fs_7825/pcie7825_gui/src/time_space_plot.py#L675)
- [time_space_plot.py](/E:/codes/das_fs_7825/pcie7825_gui/src/time_space_plot.py#L747)

修改前：

- 每次 `update_data()` 把 `phase_2d` 放入 `deque`
- `_update_display()` 中取最近若干帧，执行 `np.hstack(recent_frames)`
- 再做空间裁剪、时间/空间降采样、转置、`setImage(...)`

问题：

- 每次刷新都需要全量拼接最近窗口中的数据
- 对大矩阵场景开销较大
- 数据量大时会放大内存复制和 CPU 开销

修改后：

- 不再保存原始帧列表
- 直接维护固定尺寸的二维显示缓冲区：
  - `self._display_buffer`
  - `self._display_block_width`
  - `self._display_space_count`
  - `self._valid_block_count`
- 新数据到来后处理流程改为：
  1. `reshape` 为 `(fbg_num, frame_num)`
  2. 根据当前参数裁剪空间范围
  3. 进行时间/空间降采样
  4. 得到单次显示块 `display_block`
  5. 将该块写入固定尺寸滚动显示缓冲区
  6. 定时器统一触发 `setImage(...)`

滚动策略：

- 未满窗口时顺序写入
- 满窗口后按块左移，只保留最近 `window_frames` 个显示块

附加改动：

- `ImageItem` 改为 `pg.ImageItem(axisOrder="row-major")`
- `setImage(display_data.T, autoLevels=False)` 与 `setLevels((vmin, vmax))` 分离
- 参数变更时通过 `_invalidate_display_buffer()` 丢弃旧显示缓冲区并等待按新参数重建

目的：

- 从“每次全量重建显示矩阵”切换为“固定尺寸滚动显示”
- 降低大窗口实时刷新时的复制成本

## 3. 运行时行为核对

本次核对采用 `QT_QPA_PLATFORM=offscreen` 方式进行，不依赖实际屏幕显示。

### 3.1 Raw 曲线核对结果

核对内容：

- `plot_curve_1[0]` 是否创建成功
- 3 个 PyQtGraph 优化调用是否生效
- 曲线是否按整数显示
- Y 轴标签是否改为 `Amp.`
- 1 秒节流内再次调用时是否保留原曲线数据

核对结果：

- `raw_curve_created = True`
- `raw_clip_to_view = True`
- `raw_downsample_method = 'peak'`
- `raw_skip_finite = True`
- `raw_curve_dtype = int32`
- `raw_curve_values = [0, 1, 2, 3, 4, 5, 6, 7]`
- `raw_y_label = 'Amp.'`
- 在 1 秒节流窗口内再次调用 `_update_raw_display()` 时，曲线保持第一次数据不变

结论：

- Tab1 Raw 曲线优化项已生效
- Raw 整数显示已生效
- Raw GUI 刷新节流逻辑已按 `1.0 s` 工作

### 3.2 Time-Space 核对结果

核对内容：

- `PLOT` 启用后定时器是否启动
- `update_data()` 后是否通过固定显示缓冲区保存数据
- 窗口块数达到上限后是否停止增长并进入滚动模式
- `pending_update` 是否在 `_process_pending_update()` 后被清空

测试参数：

- `fbg_num = 6`
- `frame_num = 4`
- `window_frames = 3`
- `time_downsample = 2`
- `space_downsample = 2`
- `distance_range = [1, 6)`

核对结果：

- `timespace_timer_active = True`
- `timespace_block_width = 2`
- 固定显示缓冲区尺寸始终保持为 `(3, 6)`
- `valid_block_count` 变化为 `[1, 2, 3, 3, 3]`
- `image_item.image` 尺寸变化为 `[(2, 3), (4, 3), (6, 3), (6, 3), (6, 3)]`
- `_pending_update` 在处理完成后为 `False`

结论：

- Tab2 已启用真正的定时合并刷新
- 显示缓冲区为固定尺寸
- 窗口填满后保持滚动，不再通过 `np.hstack(...)` 全量扩展

## 4. 风险与说明

### 4.1 Raw 部分

- 当前改动只影响 Raw 曲线显示，不影响 FFT 的采样率定义
- FFT 仍按原有逻辑在后台线程中计算

### 4.2 Time-Space 部分

- 目前时间轴宽度仍按“原始帧数 × 有效块数 / scan_rate”计算
- 显示缓冲区中保存的是“按当前参数降采样后的显示块”，不是原始全分辨率数据
- 当窗口参数、时空范围、降采样参数变化时，会主动重建显示缓冲区

### 4.3 兼容性

- 本次修改没有改变对外接口
- 也没有改动主窗口与设备 API 之间的数据读取协议
- 重点是提升绘图路径的显示效率与行为一致性

## 5. 总结

本次优化完成了以下 5 个目标：

1. Tab1 Raw 曲线补充 PyQtGraph 大曲线优化调用
2. Raw GUI 刷新节流改为 `1.0 s`
3. Raw 曲线改为显示整数原值，去除电压归一化和 `V` 单位
4. Tab2 启用真正的 `QTimer + pending_update` 合并刷新
5. Tab2 用固定尺寸滚动显示缓冲区替代 `np.hstack(...)` 全量拼接

从运行时核对结果看，这些改动均已按预期生效。
