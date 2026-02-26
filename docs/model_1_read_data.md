# WFBG-7825 数据读取机制技术文档

## 概述

本文档详细分析WFBG-7825 DAS上位机软件的数据读取机制，包括Raw数据和Phase数据的读取流程、间隔控制、数据量控制等关键技术细节。

## 1. 数据读取总体架构

### 1.1 读取线程架构
- **主线程**：GUI界面，负责用户交互和数据显示
- **采集线程**：`AcquisitionThread`，负责数据读取和预处理
- **API层**：`WFBG7825API`，负责与硬件DLL的交互

### 1.2 数据流向
```
硬件缓冲区 -> DLL API -> Python API -> 采集线程 -> GUI主线程
```

## 2. Raw数据读取机制

### 2.1 读取流程

#### 数据量计算
```python
# acquisition_thread.py:195
points_per_ch = self._total_point_num * self._frame_num
```
- `total_point_num`：每次扫描的采样点数（默认20480点）
- `frame_num`：帧数（默认1024帧）
- **单次读取数据量** = 20480 × 1024 = 20,971,520 点/通道

#### 数据类型和大小
- **数据类型**：`np.int16`（16位有符号整数）
- **单通道数据量**：20,971,520 × 2字节 ≈ **40MB**
- **双通道数据量**：20,971,520 × 2通道 × 2字节 ≈ **80MB**

#### 具体读取过程
```python
# acquisition_thread.py:193-204
def _read_raw_data(self):
    """Read raw/amplitude data."""
    points_per_ch = self._total_point_num * self._frame_num

    # 调用API读取数据
    data, points_returned = self.api.read_data(points_per_ch, self._channel_num)
    self._bytes_acquired += len(data) * 2

    # 多通道数据重塑
    if self._channel_num > 1:
        data = data.reshape(-1, self._channel_num)

    # 存储待发送数据
    self._pending_raw_data = (data, self._data_source, self._channel_num)
    self._emit_if_ready()
```

### 2.2 缓冲区等待机制

#### 期望数据点计算
```python
# acquisition_thread.py:124-127
if self._data_source == DataSource.PHASE:
    expected_points = self._fbg_num_per_ch * self._frame_num
else:
    expected_points = self._total_point_num * self._frame_num
```

#### 轮询等待流程
```python
# acquisition_thread.py:131-144
while self._running:
    points_in_buffer = self.api.query_buffer_points()

    if points_in_buffer >= expected_points:
        break  # 数据足够，开始读取

    # 动态调整轮询间隔
    self._adjust_polling_interval(points_in_buffer, expected_points)
    time.sleep(self._current_polling_interval)
    wait_count += 1

    if wait_count > 5000:
        # 超时处理
        break
```

### 2.3 动态轮询间隔控制

#### 轮询间隔配置
```python
# config.py:198-203
POLLING_CONFIG = {
    'high_freq_interval_ms': 1,      # 高频轮询：1ms
    'low_freq_interval_ms': 10,      # 低频轮询：10ms
    'buffer_threshold_high': 0.8,    # 高阈值：80%
    'buffer_threshold_low': 0.3,     # 低阈值：30%
}
```

#### 自适应调整逻辑
```python
# acquisition_thread.py:260-269
def _adjust_polling_interval(self, points_in_buffer: int, expected_points: int):
    buffer_usage_ratio = points_in_buffer / expected_points

    if buffer_usage_ratio >= 0.8:           # 缓冲区≥80%满
        self._current_polling_interval = 0.001   # 1ms高频轮询
    elif buffer_usage_ratio <= 0.3:         # 缓冲区≤30%满
        self._current_polling_interval = 0.01    # 10ms低频轮询
```

## 3. Phase数据读取机制

### 3.1 读取流程差异

#### 数据量计算详解
```python
# acquisition_thread.py:220
fbg_points_per_ch = self._fbg_num_per_ch * self._frame_num
```

**Phase数据量计算实例**：
- `fbg_num_per_ch`：通过峰值检测确定的FBG数量（如223个）
- `frame_num`：读取帧数（如1024帧）
- **总数据点数** = 223 × 1024 = **228,352 点/通道**

**重要理解**：
- **228,352** 不是采样点数，而是 `FBG数量 × 帧数`
- 前面板显示的"Points"值（如9728）是每次扫描的采样点数
- Phase数据读取基于FBG数量，与采样点数无直接关系
- 这228,352个数据点代表223个FBG在1024帧时间内的相位值

**数据结构说明**：
```
phase_data.shape = (1, 228352)  # 单通道
# 重塑后用于时空显示：
time_space_data.shape = (1024, 1, 223)  # 1024帧 × 1通道 × 223个FBG
```

#### 关键参数差异
- **Raw数据**：基于`point_num_per_scan`（采样点数）
- **Phase数据**：基于`fbg_num_per_ch`（每通道FBG数量）
- **数据类型**：`np.int32`（32位有符号整数）

#### 数据量对比
| 模式 | 计算基础 | 典型值示例 | 计算公式 | 单通道数据量 |
|------|----------|------------|----------|-------------|
| Raw | `point_num × frame_num` | 9728 × 1024 | 约10M点 | ~20MB |
| Phase | `fbg_num × frame_num` | 223 × 1024 | 228K点 | ~900KB |

**Phase数据特殊说明**：
- 虽然只有223个有效FBG点，但API返回228,352个数据点
- 这包含了完整的phase数据阵列，FBG分布其中
- 实际显示时会根据FBG位置提取有效数据

### 3.2 额外的Monitor数据
```python
# acquisition_thread.py:218-225
# Phase模式下同时读取监控数据
try:
    monitor_data = self.api.read_monitor_data(self._fbg_num_per_ch, self._channel_num)
    self._pending_monitor_data = (monitor_data, self._channel_num)
except WFBG7825Error as e:
    log.warning(f"Monitor data read failed (non-critical): {e}")
```

## 4. GUI更新频率控制

### 4.1 更新间隔限制
```python
# acquisition_thread.py:22
MIN_GUI_UPDATE_INTERVAL_MS = 50  # 最大20 FPS

# acquisition_thread.py:229-236
def _emit_if_ready(self):
    current_time = time.perf_counter() * 1000
    elapsed = current_time - self._last_gui_update_time

    if elapsed < MIN_GUI_UPDATE_INTERVAL_MS:
        return  # 跳过本次更新
```

### 4.2 Raw数据特殊限制
```python
# main_window.py:1088-1094
current_time = time.time()
if (current_time - self._last_raw_display_time) >= 1.0:  # Raw数据每秒最多更新1次
    try:
        self._update_raw_display(data, channel_num)
        self._gui_update_count += 1
        self._last_raw_display_time = current_time
```

## 5. 性能问题分析

### 5.1 当前存在的问题

#### 数据量过大
- **Raw模式**：单次读取40-80MB数据
- **内存分配**：频繁的大内存分配和释放
- **数据传输**：大量数据在线程间传递

#### 处理延迟
- **缓冲区查询慢**：`query_buffer_points took 120.6 ms`
- **循环耗时长**：`Slow loop iteration: 1267.1ms`
- **GUI阻塞**：大数据量处理阻塞主线程

### 5.2 数据量控制的可行性

#### 当前控制参数
```python
# 可通过以下参数控制数据量
self._frame_num = params.display.frame_num      # 帧数（1-2048）
self._total_point_num = params.basic.point_num_per_scan  # 采样点数
```

#### 控制策略建议
1. **降低frame_num**：从1024降至256或128
2. **分块读取**：将大块数据分成小块处理
3. **降采样**：对Raw数据进行降采样后再处理
4. **异步处理**：将数据处理移至后台线程

## 6. 读取间隔控制机制

### 6.1 轮询间隔动态调整
- **高负载时**：1ms高频轮询，确保数据及时读取
- **低负载时**：10ms低频轮询，降低CPU占用
- **阈值驱动**：根据缓冲区使用率自动调整

### 6.2 读取触发条件
- **条件**：`points_in_buffer >= expected_points`
- **超时**：最大等待5000次轮询（约50秒）
- **异常处理**：网络/硬件异常时的恢复机制

## 7. 优化建议

### 7.1 短期优化
1. **减小frame_num**：从1024降至256
2. **增加GUI更新间隔**：从50ms增至200ms
3. **Raw数据降采样**：从全数据降至1/10或1/20

### 7.2 长期优化
1. **数据流水线**：实现生产者-消费者模式
2. **内存池**：预分配固定大小缓冲区
3. **多线程处理**：FFT计算移至独立线程
4. **压缩传输**：对大数据块进行压缩

## 8. Time-Space数据流分析

### 8.1 Phase数据的时空转换

#### 数据维度变化过程
```python
# 原始接收：(1, 228352)
# -> 缓冲区累积：(window_frames, 1, 228352)
# -> FBG范围提取：(window_frames, 1, 60)  # [40:100]范围
# -> 最终显示：(60, window_frames)  # 转置后
```

#### 窗口机制解析
```python
# time_space_plot.py:63-64
self._max_window_frames = 100    # 最大缓冲帧数
self._window_frames = 5          # 显示窗口帧数（用户可调整1-50）
```

**窗口机制作用**：
- **缓冲区**：保存最近100帧数据，旧数据自动删除
- **显示窗口**：从缓冲区取最近N帧用于时空显示
- **用户可调**：通过界面"Window Frames"控制时间窗口大小
- **内存优化**：避免无限制累积数据导致内存溢出

#### 实际数据流示例
根据日志 `original=(12, 1, 228352), display=(60, 12)`：
```
1. API读取：(1, 228352) = 1帧 × 228,352个数据点
2. 缓冲累积：(12, 1, 228352) = 12帧时间窗口
3. 空间提取：(12, 1, 60) = 选择FBG[40:100]共60个点
4. 显示转置：(60, 12) = 60个FBG × 12个时间点
```

### 8.2 坐标系统

#### 时间轴计算
```python
time_duration_s = window_frames / scan_rate
# 示例：12帧 / 2000Hz = 0.006秒
```

#### 空间轴含义
- **Y轴(垂直)**：FBG传感点位置索引
- **X轴(水平)**：时间维度
- **颜色**：相位变化幅度

## 9. 总结

Raw数据和Phase数据读取机制基本相同，主要差异在于：
- **数据量大小**：Raw数据量是Phase数据的20倍左右（实际测试）
- **读取参数**：Raw基于采样点数，Phase基于FBG数量
- **数据类型**：Raw为int16，Phase为int32
- **更新频率**：Raw限制为1秒1次，Phase可达20FPS

**关键发现**：
1. **228352 = 223个FBG × 1024帧**，不是采样点数
2. **Time-Space窗口机制**：保留100帧缓冲，显示最近N帧
3. **完整数据传输**：虽然只有223个有效FBG，但传输完整phase阵列
4. **用户可控参数**：窗口帧数、时空范围、采样参数均可调整

当前性能问题主要源于数据处理量和更新频率，可通过参数调整和算法优化来改善。