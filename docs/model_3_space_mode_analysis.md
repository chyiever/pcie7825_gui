# WFBG-7825 Space模式FBG指定传感点数据提取技术文档

## 概述

本文档详细分析WFBG-7825 DAS上位机软件中Space模式的实现机制，包括指定FBG传感点波形数据的提取、处理和显示流程。Space模式允许用户观察单个FBG传感点在时间序列上的相位变化。

## 1. Space模式概念

### 1.1 模式对比
- **Time模式**：显示多个时间帧的FBG空间分布（叠加显示）
- **Space模式**：显示单个FBG传感点的时间序列变化（指定位置波形）

### 1.2 核心参数
- **FBG Idx** (`region_index`)：用户指定的FBG传感点索引
- **Frame Num**：时间序列帧数
- **Data Structure**：从多帧数据中提取单点时间序列

## 2. 线程架构和数据流

### 2.1 线程架构
```
[硬件设备]
    ↓
[WFBG7825API - DLL接口层]
    ↓
[AcquisitionThread - 采集线程]
    ↓ (pyqtSignal)
[MainWindow - GUI主线程]
    ↓
[_update_phase_display - 数据处理]
    ↓
[PyQtGraph Plot - 图形显示]
```

### 2.2 关键线程和组件

#### 采集线程 (AcquisitionThread)
- **文件**：`src/acquisition_thread.py`
- **作用**：后台数据采集，避免阻塞GUI
- **关键方法**：
  - `_read_phase_data()` - 读取phase数据
  - `_emit_if_ready()` - 控制发射频率

#### GUI主线程 (MainWindow)
- **文件**：`src/main_window.py`
- **作用**：用户交互和数据显示
- **关键方法**：
  - `_on_phase_data()` - 接收phase数据信号
  - `_update_phase_display()` - 处理和显示数据

## 3. 数据读取机制

### 3.1 Phase数据读取
```python
# acquisition_thread.py:218-228
def _read_phase_data(self):
    """Read phase data using fbg_num semantics."""
    fbg_points_per_ch = self._fbg_num_per_ch * self._frame_num

    phase_data, points_returned = self.api.read_phase_data(fbg_points_per_ch, self._channel_num)
    self._bytes_acquired += len(phase_data) * 4

    if self._channel_num > 1:
        phase_data = phase_data.reshape(-1, self._channel_num)

    self._pending_phase_data = (phase_data, self._channel_num)
```

**关键变量**：
- `self._fbg_num_per_ch`：每通道FBG数量（来自峰值检测）
- `self._frame_num`：帧数（默认1024）
- `fbg_points_per_ch`：总数据点数 = FBG数量 × 帧数

### 3.2 数据结构
```python
# 实际数据示例
fbg_num_per_ch = 223        # 检测到的FBG数量
frame_num = 1024           # 帧数
total_points = 223 × 1024 = 228,352  # API返回的数据点数

# Phase数据结构
phase_data.shape = (228352,)  # 一维数组，包含所有FBG在所有帧的数据
# 数据排列：[frame0_fbg0, frame0_fbg1, ..., frame0_fbg222, frame1_fbg0, ...]
```

### 3.3 信号发射控制
```python
# acquisition_thread.py:241-255
def _emit_if_ready(self):
    """Emit pending data signals if enough time has passed."""
    current_time = time.perf_counter() * 1000
    elapsed = current_time - self._last_gui_update_time

    if elapsed < MIN_GUI_UPDATE_INTERVAL_MS:  # 50ms限制
        return

    if self._pending_phase_data is not None:
        phase_data, channel_num = self._pending_phase_data
        self.phase_data_ready.emit(phase_data, channel_num)  # 发射信号到GUI
        self._pending_phase_data = None
```

**频率控制**：`MIN_GUI_UPDATE_INTERVAL_MS = 50` (最大20 FPS)

## 4. Space模式数据提取算法

### 4.1 信号接收和预处理
```python
# main_window.py:1255-1268
def _on_phase_data(self, data: np.ndarray, channel_num: int):
    self._data_count += 1

    # 数据保存（如果启用）
    if self.data_saver is not None and self.data_saver.is_running:
        self.data_saver.save_frame(data)

    try:
        self._update_phase_display(data, channel_num)  # 核心处理函数
    except Exception as e:
        log.exception(f"Error in _update_phase_display: {e}")
```

### 4.2 Space模式核心算法
```python
# main_window.py:1360-1394
def _update_phase_display(self, data: np.ndarray, channel_num: int):
    frame_num = self.params.display.frame_num           # 1024
    fbg_num = self._fbg_num_per_ch                     # 223

    # 应用弧度转换（仅显示，存储数据不变）
    display_data = data
    if self.params.display.rad_enable:
        display_data = data.astype(np.float64) / 32767.0 * np.pi

    if self.params.display.mode == DisplayMode.SPACE:
        region_idx = min(self.params.display.region_index, fbg_num - 1)  # 用户指定的FBG索引

        if channel_num == 1:
            space_data = []
            for i in range(frame_num):                  # 遍历所有帧
                idx = region_idx + fbg_num * i          # 计算在一维数组中的位置
                if idx < len(display_data):
                    space_data.append(display_data[idx]) # 提取指定FBG在第i帧的数据
            space_data = np.array(space_data)            # 转换为numpy数组

            # 更新图形显示
            self.plot_curve_1[0].setData(space_data)    # 绘制时间序列波形
```

### 4.3 关键算法解析

#### 索引计算公式
```python
idx = region_idx + fbg_num * i
```

**公式解释**：
- `region_idx`：用户指定的FBG传感点索引（0到222）
- `fbg_num`：每帧FBG总数（223）
- `i`：帧索引（0到1023）
- `idx`：在一维phase_data数组中的绝对位置

**数据排列示例**：
```
phase_data = [f0_fbg0, f0_fbg1, ..., f0_fbg222, f1_fbg0, f1_fbg1, ..., f1_fbg222, ...]
索引:         0       1            222      223     224           445

如果region_idx=5（要提取第5个FBG），则：
- 第0帧：idx = 5 + 223*0 = 5
- 第1帧：idx = 5 + 223*1 = 228
- 第2帧：idx = 5 + 223*2 = 451
- ...
```

#### 双通道处理
```python
# main_window.py:1400-1418
else:  # channel_num > 1
    if len(display_data.shape) == 1:
        display_data = display_data.reshape(-1, channel_num)  # 重塑为多通道

    for ch in range(min(channel_num, 2)):
        space_data = []
        for i in range(frame_num):
            idx = region_idx + fbg_num * i
            if idx < len(display_data):
                space_data.append(display_data[idx, ch])  # 提取特定通道数据
        self.plot_curve_1[ch].setData(np.array(space_data))
```

## 5. 用户界面控制

### 5.1 控制界面元素
```python
# main_window.py:461-478
self.mode_space_radio = QRadioButton("Space")           # Space模式选择
self.region_index_spin = QSpinBox()                     # FBG索引输入
self.region_index_spin.setRange(0, 65535)              # 索引范围
self.region_index_spin.setValue(0)                     # 默认第0个FBG
```

### 5.2 参数配置
```python
# main_window.py:893-894
params.display.mode = DisplayMode.SPACE if self.mode_space_radio.isChecked() else DisplayMode.TIME
params.display.region_index = self.region_index_spin.value()
```

**配置参数**（config.py）：
```python
@dataclass
class DisplayParams:
    mode: int = DisplayMode.TIME          # 显示模式
    region_index: int = 0                 # FBG索引（Space模式用）
    frame_num: int = 1024                # 帧数
    rad_enable: bool = False             # 弧度转换开关
```

## 6. 数据转换和单位

### 6.1 原始数据特性
- **数据类型**：`np.int32`（32位有符号整数）
- **数值范围**：-32768 到 +32767
- **物理意义**：相位信息（归一化后的数字量）

### 6.2 弧度转换
```python
# main_window.py:1369-1370
if self.params.display.rad_enable:
    display_data = data.astype(np.float64) / 32767.0 * np.pi
```

**转换公式**：
- 原始值 → 归一化 → 弧度
- `rad_value = int_value / 32767.0 * π`
- 范围：`[-π, +π]` 弧度

### 6.3 显示与存储分离
- **显示数据**：可选择弧度转换，便于用户理解
- **存储数据**：始终保持原始整数格式，确保精度

## 7. 性能优化

### 7.1 Tab切换优化
```python
# main_window.py:1372-1373
# Check which tab is currently active for performance optimization
current_tab = self.plot_tabs.currentIndex() if hasattr(self, 'plot_tabs') else 0

# main_window.py:1387-1388
# Update Tab1 (traditional plots) only if it's active or if no tabs
if current_tab == 0 or current_tab is None:
```

**优化策略**：
- 仅更新当前激活的Tab页面
- 避免后台Tab的无效计算
- 提高GUI响应速度

### 7.2 频率控制
- **采集线程**：50ms最小间隔（最大20 FPS）
- **GUI更新**：仅在必要时更新图形

### 7.3 内存优化
- **数据复用**：避免不必要的数组复制
- **条件计算**：弧度转换仅在启用时执行

## 8. Time-Space集成

### 8.1 双重显示支持
Space模式同时支持两种可视化：
1. **Tab1**：传统1D时间序列波形
2. **Tab2**：Time-Space 2D热力图

```python
# main_window.py:1396-1399
# Update Tab2 (time-space plot) if it's active and widget exists
if current_tab == 1 and hasattr(self, 'time_space_widget'):
    # Send data to time-space widget
    self.time_space_widget.update_data(display_data, channel_num)
```

### 8.2 数据传递
- **Tab1**：使用提取的`space_data`数组
- **Tab2**：传递完整的`display_data`进行2D可视化

## 9. 错误处理和边界检查

### 9.1 索引边界保护
```python
# main_window.py:1376
region_idx = min(self.params.display.region_index, fbg_num - 1)
```

### 9.2 数据有效性检查
```python
# main_window.py:1364-1365
if fbg_num == 0:
    return  # 未进行峰值检测时直接返回

# main_window.py:1382-1383
if idx < len(display_data):
    space_data.append(display_data[idx])  # 仅在索引有效时添加数据
```

### 9.3 异常处理
```python
# main_window.py:1267-1268
except Exception as e:
    log.exception(f"Error in _update_phase_display: {e}")
```

## 10. 关键变量总览

### 10.1 全局状态变量
| 变量名 | 类型 | 作用 | 来源 |
|--------|------|------|------|
| `self._fbg_num_per_ch` | int | 每通道FBG数量 | 峰值检测结果 |
| `self.params.display.frame_num` | int | 时间帧数 | 用户配置 |
| `self.params.display.region_index` | int | 目标FBG索引 | 用户输入 |
| `self.params.display.mode` | DisplayMode | 显示模式 | 用户选择 |
| `self.params.display.rad_enable` | bool | 弧度转换开关 | 用户配置 |

### 10.2 数据处理变量
| 变量名 | 类型 | 作用 | 范围 |
|--------|------|------|------|
| `phase_data` | np.ndarray | 原始phase数据 | 一维数组，长度228352 |
| `display_data` | np.ndarray | 显示用数据 | 可能经过弧度转换 |
| `space_data` | list/np.ndarray | 提取的时间序列 | 长度等于frame_num |
| `region_idx` | int | 边界检查后的FBG索引 | 0 到 fbg_num-1 |
| `idx` | int | 一维数组中的绝对位置 | 索引计算结果 |

### 10.3 界面控制变量
| 控件名 | 类型 | 作用 | 范围 |
|--------|------|------|------|
| `self.mode_space_radio` | QRadioButton | Space模式选择 | True/False |
| `self.region_index_spin` | QSpinBox | FBG索引输入 | 0-65535 |
| `self.plot_curve_1[ch]` | PlotDataItem | 图形曲线对象 | PyQtGraph |

## 11. 总结

Space模式通过精确的索引计算算法，从多帧phase数据中提取指定FBG传感点的时间序列：

### 11.1 核心特点
1. **精确定位**：通过`region_idx + fbg_num * i`公式定位数据
2. **实时处理**：采集线程与GUI线程分离，保证响应性
3. **双重可视化**：支持1D波形和2D热力图
4. **灵活转换**：支持原始整数和弧度显示单位

### 11.2 关键优势
- **用户友好**：直观的FBG索引选择
- **性能优化**：Tab切换和频率控制
- **数据完整性**：显示与存储分离
- **错误处理**：完善的边界检查

### 11.3 应用场景
- **单点监测**：观察特定位置的振动/应变变化
- **时域分析**：分析传感点的时间特性
- **故障诊断**：定位异常传感点
- **信号特征分析**：提取特定位置的信号特征

Space模式为DAS系统提供了强大的单点时域分析能力，是phase数据处理的重要组成部分。