# 2026-04-28 Phase 模式 PSD 卡顿优化记录

## 1. 问题现象

在完成寻峰后进入 `Phase` 模式，采样率设置为 `20000 Hz`，如果同时启用：

- `Time Domain`
- `Spectrum`
- `PSD`

则主界面会明显卡顿，严重时接近“假死”。

如果仅启用 `Time Domain`，软件可以正常运行。

## 2. 根因分析

问题不在 PSD 公式本身，而在 `Phase` 模式下频谱更新链路的线程模型和刷新策略。

### 2.1 原有线程关系

- 采集线程：`src/acquisition_thread.py`
- GUI 主线程：`src/main_window.py`
- FFT worker 线程：`src/fft_worker.py`

原实现里：

1. `Raw` 模式的 FFT/PSD 走 `FFTWorkerThread` 异步计算。
2. `Phase` 模式的频谱/PSD 在主线程的 `_update_spectrum(...)` 中同步计算。
3. `Phase` 模式下时域图和频谱图的更新都落在 GUI 主线程中执行。

这意味着在 `Phase` 模式下，只要频谱开启，GUI 线程就需要同时承担：

- 时域曲线 `setData(...)`
- PSD/FFT 数值计算
- 频谱曲线 `setData(...)`
- 坐标轴与自动缩放更新

当采样率较高、界面持续刷新时，主线程会被这一整条链路压住。

### 2.2 额外放大卡顿的两个因素

#### 因素 A：Phase 频谱没有单独节流

`Raw` 模式已有独立的 FFT 更新节流；
`Phase` 模式原先没有对应的频谱节流，GUI 每次收到相位数据显示时都可能立刻做一次频谱计算与重绘。

#### 因素 B：频谱更新与时域开关耦合

原逻辑中，`Phase` 模式的频谱更新被写在 `Time Domain` 分支内部。

直接结果是：

- 只开频谱、不看时域时，频谱更新逻辑并不独立。
- 同时开时域和 PSD 时，主线程在同一次 GUI 更新里既画时域又算频谱。

## 3. 优化目标

本次优化目标是：

1. `Phase` 模式的 FFT/PSD 也改为后台线程计算。
2. 为 `Phase` 频谱增加独立刷新节流，避免高频重算。
3. 拆开“时域图显示”和“频谱更新”的逻辑耦合。
4. 降低频谱绘图本身的重绘压力。

## 4. 实现方案

### 4.1 统一 FFT worker，支持 Raw 与 Phase

修改文件：

- `src/fft_worker.py`

调整点：

1. `FFTWorkerThread.calculate_fft(...)` 新增参数：
   - `sample_rate`
   - `data_type`
   - `psd_mode`
2. `fft_ready` 信号携带完整展示上下文：
   - `freq`
   - `spectrum`
   - `df`
   - `sample_rate`
   - `data_type`
   - `psd_mode`
3. Worker 不再只假定 `Raw short + 1 GHz`，也可以处理：
   - `Phase int + 20000 Hz`

这样 `Phase` 模式的 PSD 计算也能彻底离开 GUI 主线程。

### 4.2 Phase 频谱独立节流

修改文件：

- `src/config.py`
- `src/main_window.py`

新增配置：

```python
PHASE_DISPLAY_CONFIG = {
    'spectrum_update_s': 0.25,
}
```

含义：

- `Phase` 模式下频谱/PSD 最快每 `250 ms` 请求一次后台 FFT。
- 时域图仍可按原 GUI 数据到达频率刷新。
- 这样可以保留时域响应，同时避免频谱重算过密。

### 4.3 拆开时域图与频谱更新的耦合

修改文件：

- `src/main_window.py`

调整前：

- `Phase` 模式下的频谱更新逻辑写在 `Time Domain` 分支内部。

调整后：

- `Time Domain` 是否显示，只影响 `plot_widget_1` 是否更新。
- `Spectrum/PSD` 是否更新，由独立的 `spectrum_enabled` 逻辑控制。
- 因此：
  - 只开频谱也能独立更新。
  - 同时开时域和频谱时，频谱不再在主线程同步计算。

### 4.4 优化 Phase SPACE 模式取数

修改文件：

- `src/main_window.py`

原实现使用 Python 循环逐帧拼接 `space_data`。

本次新增：

- `_extract_phase_space_data(...)`

改为使用 `numpy` 切片抽取 Phase SPACE 序列，减少 Python 层循环开销。

### 4.5 降低频谱曲线重绘压力

修改文件：

- `src/main_window.py`

为 `self.spectrum_curve` 增加：

```python
self.spectrum_curve.setClipToView(True)
self.spectrum_curve.setDownsampling(auto=True, method="peak")
self.spectrum_curve.setSkipFiniteCheck(True)
```

目的：

- 缩放或大点数情况下减少不必要的绘图负担。

## 5. 本次修改涉及的关键路径

### 5.1 Phase 显示链路

`AcquisitionThread.phase_data_ready`

-> `MainWindow._on_phase_data(...)`

-> `MainWindow._update_phase_display(...)`

-> `MainWindow._update_spectrum(...)`

-> `MainWindow._request_spectrum_update(...)`

-> `FFTWorkerThread.calculate_fft(...)`

-> `FFTWorkerThread.run()`

-> `MainWindow._on_fft_ready(...)`

-> `MainWindow._display_fft_result(...)`

### 5.2 Raw 显示链路

`Raw` 模式继续保留原先“后台 FFT worker + Raw 自身节流”的设计，只把 worker 接口统一为通用版。

## 6. 验证情况

### 6.1 语法编译

执行：

```bash
python -m py_compile src/main_window.py src/fft_worker.py src/config.py src/acquisition_thread.py
```

结果：

- 通过

### 6.2 FFT worker 最小运行验证

执行了一个基于 `QCoreApplication` 的最小脚本，分别验证：

1. `Raw short + 1e9 sample_rate + PSD=False`
2. `Phase int + 20000 sample_rate + PSD=True`

两次请求都成功返回结果，说明：

- 新信号签名正确
- Worker 可同时处理 Raw/Phase 两种频谱请求
- `sample_rate/data_type/psd_mode` 透传正确

## 7. 结果

本次改动后，`Phase` 模式下：

1. PSD 计算不再阻塞 GUI 主线程。
2. 频谱/PSD 有独立节流，不会跟随每次相位数据显示都立即重算。
3. `Time Domain` 与 `Spectrum/PSD` 的更新逻辑解耦。
4. 频谱曲线绘图本身也做了额外减负。

因此，针对“寻峰后进入 Phase 模式，`20000 Hz` 下同时勾选时域图和 PSD 图导致界面卡死”的问题，本次修改从线程模型和刷新策略两侧同时做了修复。

## 8. 后续可选优化

如果后续还要继续压缩高负载场景下的 UI 压力，可以考虑：

1. 为 `Phase` 时域图也增加单独刷新节流。
2. 将 `FFTWorkerThread` 改为常驻循环 worker，而不是单次请求线程。
3. 对 `Phase` 频谱输入点数做可配置上限控制。
4. 为频谱自动缩放增加更保守的刷新策略，减少频繁 `autoRange`。
