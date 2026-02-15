# WFBG-7825 Python GUI 开发日志

## 项目概述

- **项目名称**: WFBG-7825 分布式光纤传感系统 Python GUI
- **开发日期**: 2026-02-15
- **目标目录**: `E:/codes/das_fs_7825/7825GUIpy/`
- **参考项目**: PCIe-7821 Python GUI (`D:/OneDrive - EVER/00_KY/DAS-器件测试、上位机开发/BX/PCIe-7821/pcie7821_gui/`)
- **硬件文档**: `E:/codes/das_fs_7825/PCIe-WFBG-7825/doc/readme.txt`
- **C Demo 参考**: `E:/codes/das_fs_7825/PCIe-WFBG-7825/windows issue/demo/WFBG_7825_Dem_dll_ver/`

---

## 一、需求分析与架构设计

### 1.1 产品背景

PCIe-WFBG-7825 是上海比宣信息科技有限公司推出的 **弱光纤光栅 (WFBG) 阵列 DAS 专用板卡**，与通用型 PCIe-7821 有显著差异。7825 内置自动寻峰、相干衰落抑制、解卷绕、去趋势滤波、偏振衰落抑制等算法，适配偏振分集的 DAS 系统架构。

核心硬件规格：
- 16bits 双通道同步实时采样，1GSps 采样率
- 直流耦合，50Ω 输入阻抗
- 1.9Vpp 输入电压范围，0-250MHz 模拟带宽
- 高达 89dBc SFDR
- 2GB DDR3 高速数据缓存
- PCIe x8 接口

### 1.2 7825 vs 7821 关键差异

在开发前，首先通过详细阅读 7825 的 API 文档 (`readme.txt`)、C Demo 源码以及 7821 的完整 Python GUI 代码，梳理了以下关键差异：

| 方面 | 7821 | 7825 |
|------|------|------|
| 通道数 | 1/2/4 | 仅 1/2 |
| 数据源 | raw(0), I/Q(2), arctan(3), phase(4) | raw(0), amplitude(1), phase(2) |
| 采样率控制 | 可变 (1-32ns) | 固定 1GSps |
| 触发设置 | 3个独立函数 (`set_trig_dir`, `set_scan_rate`, `set_pulse_width`) | 1个组合函数 `set_trig_param()` |
| 相位解调参数 | 6个参数 (rate2phase, avg, merge, diff, detrend, polar) | 2个参数 (polar, detrend) |
| FBG 寻峰 | 无 | `get_peak_info`, `set_peak_info`, `get_valid_fbg_num` |
| 启动前提 | 直接启动 | 必须先运行寻峰 |
| Monitor 数据读取 | 无尺寸参数 | 需要 `fbg_num_per_ch` 参数 |
| 相位数据语义 | `point_num / merge` | `fbg_num_per_ch`（来自寻峰结果）|
| 中心频率 | 自由输入 SpinBox | ComboBox (80MHz / 200MHz) |
| rad 转换 | 有 (显示用) | 无（相位已校准）|

### 1.3 设计决策

基于差异分析，确定以下设计方案：

1. **项目结构**：完全镜像 7821 的目录布局 (`run.py`, `src/`, `libs/`, `logs/`, `output/`, `resources/`)
2. **代码复用策略**：
   - `logger.py`, `spectrum_analyzer.py`, `data_saver.py`：从 7821 复制并修改命名空间
   - `config.py`, `wfbg7825_api.py`, `acquisition_thread.py`, `main_window.py`：基于 7821 重写，融入 7825 特性
   - `main.py`, `run.py`：从 7821 复制并简单适配
3. **仿真模式**：保留 `--simulate` 参数，SimulatedAcquisitionThread 生成模拟数据用于 UI 测试

---

## 二、参考代码分析

### 2.1 7821 Python GUI 源码阅读

通过两个并行的 Explore Agent 分别对 7821 Python GUI 和 7825 C Demo + API 文档进行了详细阅读。

#### 7821 项目文件清单

```
pcie7821_gui/
├── run.py                    (25 行)  - 快速启动脚本
├── src/
│   ├── __init__.py           (6 行)   - 包标识
│   ├── main.py               (319 行) - 入口：argparse, 日志, 高DPI, QApplication
│   ├── config.py             (494 行) - 参数、枚举、验证、硬件约束
│   ├── logger.py             (395 行) - 线程感知日志 + 性能计时
│   ├── pcie7821_api.py       (717 行) - ctypes DLL 封装
│   ├── acquisition_thread.py (539 行) - QThread 采集线程
│   ├── spectrum_analyzer.py  (609 行) - FFT 频谱分析
│   ├── data_saver.py         (509 行) - 异步文件保存
│   └── main_window.py        (1537 行)- PyQt5 主窗口
├── libs/                     - DLL 存放
├── resources/                - logo.png 等
├── logs/                     - 运行日志
└── output/                   - 数据输出
```

#### 7821 关键架构模式

1. **数据流**: AcqThread → Qt Signal → MainWindow slot → 显示更新 / DataSaver
2. **GUI 节流**: 信号发射限制在 20 FPS (50ms 间隔)
3. **动态轮询**: 根据缓冲区填充率自适应调整轮询间隔 (1ms-10ms)
4. **DMA 对齐**: AlignedBuffer 类确保 4096 字节对齐
5. **线程安全**: DLL 调用使用 `threading.Lock`

### 2.2 7825 C Demo 源码阅读

C Demo 位于 `WFBG_7825_Dem_dll_ver/` 目录，包含以下文件：

| 文件 | 行数 | 内容 |
|------|------|------|
| `WFBG7825_DEMO.c` | 759 | 主程序：采集循环、频谱分析、寻峰、文件保存 |
| `WFBG7825_DEMO.h` | 99 | LabWindows/CVI UI 资源头文件 |
| `wfbg7825_api.h` | 28 | DLL 导入声明 (18个API函数) |
| `src/wfbg7825_api.h` | 28 | 纯 C 函数声明 |
| `src/wfbg7825.c` | 142 | API 封装层：参数校验 + 调用 base 函数 |
| `src/wfbg7825_base.c` | 606 | 底层硬件抽象：寄存器读写、寻峰算法、DMA |
| `src/wfbg7825_base.h` | 69 | 底层接口声明 (32个内部函数) |
| `BX_Audio.h` | 31 | 音频播放接口 |

#### C Demo 中的关键实现细节

- **内存对齐**: `aligned_malloc()` / `aligned_free()` 实现 4096 字节对齐
- **寻峰算法**: 1024帧幅值平均 + 4点比较的局部极大值检测
- **峰值标记**: 编码为 32 位标志位（每个寄存器 4 个数据点）
- **频谱分析**: 带 Hann 窗的 FFT 功率谱密度计算

### 2.3 API 文档 (readme.txt) 关键信息

完整记录了 18 个 DLL 接口函数的详细说明，关键要点：

1. **调用顺序**: open → set_clk_src → set_trig_param → set_point_num → set_bypass → set_upload → set_center_freq → set_phase_dem → get_peak_info → get_valid_fbg_num → start → query/read → stop → close
2. **bypass_point_num**: 必须为 4 的整数倍 (0/4/8/12...)
3. **pulse_width**: 必须为 4ns 的整数倍，最小 4ns
4. **偏振分集 + phase**: upload_ch_num 必须设为 1
5. **read_phase_data 的 fbg_num_per_ch**: = fbg_num_per_scan × N (N 为帧数)
6. **read_monitor_data**: 每次只上传一个脉冲的幅值数据，fbg_num_per_ch 必须与 get_valid_fbg_num 返回值一致
7. **数据解析规则**: raw/amplitude 用 short*，phase 用 int*；相位定点数 32767 = π, -32768 = -π
8. **p_data 地址必须 4096 对齐**

---

## 三、实现过程

### 3.1 目录结构创建与 DLL 复制

首先创建项目目录结构并复制必要文件：

```bash
mkdir -p "E:/codes/das_fs_7825/7825GUIpy/"{src,libs,logs,output,resources}

# 复制 DLL
cp "E:/codes/das_fs_7825/PCIe-WFBG-7825/windows issue/dll/x64/wfbg7825_api.dll" \
   "E:/codes/das_fs_7825/7825GUIpy/libs/"

# 复制 Logo
cp "D:/OneDrive - EVER/00_KY/.../pcie7821_gui/resources/logo.png" \
   "E:/codes/das_fs_7825/7825GUIpy/resources/"
```

DLL 文件大小: 24,576 字节 (x64 架构)。

### 3.2 实现顺序

按依赖关系从底层到顶层逐步实现：

```
1. __init__.py          → 包标识
2. logger.py            → 日志系统（最底层依赖）
3. config.py            → 参数定义（被所有模块引用）
4. spectrum_analyzer.py → FFT 分析（独立模块）
5. data_saver.py        → 文件保存（仅依赖 logger）
6. wfbg7825_api.py      → DLL 封装（依赖 config, logger）
7. acquisition_thread.py→ 采集线程（依赖 api, config, logger）
8. main_window.py       → 主窗口（依赖所有模块）
9. main.py              → 入口点（依赖 logger, main_window）
10. run.py              → 启动脚本（依赖 main）
```

### 3.3 各模块实现详情

#### 3.3.1 `src/__init__.py`

最简包标识，定义版本号和作者信息。命名空间改为 `WFBG-7825`。

#### 3.3.2 `src/logger.py` — 日志系统

从 7821 复制并修改：
- 日志命名空间: `"pcie7821"` → `"wfbg7825"`
- 保留所有功能: `ThreadFormatter`, `setup_logging`, `get_logger`, `PerformanceTimer`, `log_timing`
- 日志格式: `[elapsed_ms] [thread_name] [level] name: message`

#### 3.3.3 `src/config.py` — 配置模块

**重大改动**，核心差异体现在此：

枚举变更：
```python
# 7821: DataSource(raw=0, I_Q=2, arc=3, PHASE=4)
# 7825:
class DataSource(IntEnum):
    RAW = 0         # 原始数据
    AMPLITUDE = 1   # √(I²+Q²)
    PHASE = 2       # 相位解调数据
```

参数结构变更：
```python
# UploadParams: 移除 data_rate 字段
@dataclass
class UploadParams:
    channel_num: int = 1    # 仅支持 1/2
    data_source: int = DataSource.PHASE

# PhaseDemodParams: 6 个参数简化为 2 个
@dataclass
class PhaseDemodParams:
    polarization_diversity: bool = False
    detrend_bw: float = 0.5

# PeakDetectionParams: 全新参数类
@dataclass
class PeakDetectionParams:
    amp_base_line: int = 2000
    fbg_interval_m: float = 5.0
```

GUI 选项变更：
```python
CHANNEL_NUM_OPTIONS = [("1", 1), ("2", 2)]  # 移除 4 通道
DATA_SOURCE_OPTIONS = [("Raw", 0), ("√(I²+Q²)", 1), ("Phase", 2)]
CENTER_FREQ_OPTIONS = [("80 MHz", 80), ("200 MHz", 200)]  # 新增
# 移除: DATA_RATE_OPTIONS, RATE2PHASE_OPTIONS
```

硬件约束变更：
```python
MAX_POINT_NUM_1CH = 262144  # 保持
MAX_POINT_NUM_2CH = 131072  # 保持
# 移除: MAX_POINT_NUM_4CH = 65536
MAX_FBG_PER_PHASE_DEM = 16384  # 新增
```

光纤长度计算简化：
```python
# 7821: 需考虑 data_rate, data_source, rate2phase
# 7825: 固定 1GSps，0.1m/点
def calculate_fiber_length(point_num: int) -> float:
    return point_num * 0.1 / 1000.0  # km
```

#### 3.3.4 `src/spectrum_analyzer.py` — FFT 分析

从 7821 直接复制，仅修改文件头注释中的产品名称。功能完全一致：
- `WindowType` 枚举 (5种窗函数)
- `SpectrumAnalyzer` 基础分析器
- `RealTimeSpectrumAnalyzer` 带时域平均的实时分析器

#### 3.3.5 `src/data_saver.py` — 数据保存

从 7821 复制并修改：
- 日志命名空间: `"pcie7821"` → `"wfbg7825"`
- 文件名前缀: `eDAS` → `wfbg7825`
  - 格式: `{seq:05d}-wfbg7825-{rate:04d}Hz-{points:04d}pt-{timestamp}.{ms}.bin`
  - 示例: `00001-wfbg7825-2000Hz-0410pt-20260215T143052.256.bin`
- 保留三个类: `DataSaver` (基础), `FrameBasedFileSaver` (主要), `TimedFileSaver` (已移除，仅保留前两个)

#### 3.3.6 `src/wfbg7825_api.py` — DLL 封装

**重大重写**，包含所有 7825 特有的 API 调用。

函数原型设置 (`_setup_prototypes`)：
```python
# 18 个 DLL 函数的 ctypes 签名定义
wfbg7825_open()                          → c_int
wfbg7825_close()                         → None
wfbg7825_set_clk_src(uint)               → c_int
wfbg7825_set_trig_param(uint, uint, uint)→ c_int  # 组合调用
wfbg7825_set_origin_point_num_per_scan(uint) → c_int
wfbg7825_set_bypass_point_num(uint)      → c_int
wfbg7825_set_upload_data_param(uint, uint)→ c_int  # 无 data_rate
wfbg7825_set_center_freq(uint)           → c_int
wfbg7825_set_phase_dem_param(uint, double)→ c_int  # 仅 2 参数
wfbg7825_get_peak_info(...)              → c_int  # 新增: 8个参数
wfbg7825_set_peak_info(uint*, uint*)     → c_int  # 新增
wfbg7825_get_valid_fbg_num(uint*)        → c_int  # 新增
wfbg7825_point_num_per_ch_in_buf_query(uint*) → c_int
wfbg7825_read_data(uint, short*, uint*)  → c_int
wfbg7825_read_phase_data(uint, int*, uint*) → c_int  # fbg_num 语义
wfbg7825_read_monitor_data(uint, uint*)  → c_int  # 需要 fbg_num
wfbg7825_start()                         → c_int
wfbg7825_stop()                          → c_int
```

新增方法：
- `get_peak_info(amp_base_line, fbg_interval_m, point_num_per_scan)`: 分配 `point_num_per_scan` 大小的数组，调用 DLL 获取寻峰结果，返回 (ch0_cnt, ch0_info, ch0_amp, ch1_cnt, ch1_info, ch1_amp)
- `set_peak_info(ch0_info, ch1_info)`: 可选，用户自定义寻峰结果
- `get_valid_fbg_num()`: 获取有效 FBG 数量

关键差异实现：
```python
# 7821: 3个独立调用
api.set_trig_dir(trig_dir)
api.set_scan_rate(scan_rate)
api.set_pulse_width(pulse_width_ns)

# 7825: 1个组合调用
api.set_trig_param(trig_dir, scan_rate, pulse_width_ns)

# 7821: 3个参数
api.set_upload_data_param(ch_num, data_src, data_rate)

# 7825: 2个参数（无 data_rate）
api.set_upload_data_param(ch_num, data_src)

# 7821: 6个参数
api.set_phase_dem_param(rate2phase, space_avg, merge, diff, detrend, polar)

# 7825: 2个参数
api.set_phase_dem_param(polarization_en, detrend_bw)

# 7825 新增: 寻峰 + FBG 数量
(ch0_cnt, ch0_info, ch0_amp,
 ch1_cnt, ch1_info, ch1_amp) = api.get_peak_info(amp_base, interval, point_num)
fbg_num = api.get_valid_fbg_num()

# 7825: monitor 需要 fbg_num
monitor = api.read_monitor_data(fbg_num_per_ch, channel_num)
```

缓冲区分配：
```python
def allocate_buffers(self, point_num, channel_num, frame_num, fbg_num_per_ch=0):
    # Raw buffer (int16): point_num * channel_num * frame_num
    # Phase buffer (int32): fbg_num_per_ch * channel_num * frame_num
    # Monitor buffer (uint32): fbg_num_per_ch * channel_num
```

#### 3.3.7 `src/acquisition_thread.py` — 采集线程

基于 7821 重写，核心变更：

1. **`configure()` 方法新增 `fbg_num_per_ch` 参数**：
```python
def configure(self, params: AllParams, fbg_num_per_ch: int = 0):
    self._fbg_num_per_ch = fbg_num_per_ch  # 来自寻峰结果
```

2. **数据大小计算使用 fbg_num**：
```python
# 7821:
expected_points = self._point_num_after_merge * self._frame_num  # merge 语义

# 7825:
if self._data_source == DataSource.PHASE:
    expected_points = self._fbg_num_per_ch * self._frame_num  # FBG 语义
else:
    expected_points = self._total_point_num * self._frame_num
```

3. **数据源判断逻辑**：
```python
# 7821: data_source == DataSource.PHASE (值为 4)
# 7825: data_source == DataSource.PHASE (值为 2)
# data_source <= 1 为 raw/amplitude, == 2 为 phase
```

4. **Monitor 数据读取带 fbg_num 参数**：
```python
# 7821:
monitor = api.read_monitor_data(point_num_after_merge, channel_num)

# 7825:
monitor = api.read_monitor_data(self._fbg_num_per_ch, channel_num)
```

5. **SimulatedAcquisitionThread** 模拟数据大小也基于 fbg_num：
```python
fbg_num = max(self._fbg_num_per_ch, 100)  # 仿真时最少 100 个 FBG
points = fbg_num * self._frame_num
```

#### 3.3.8 `src/main_window.py` — 主窗口 GUI

**最大的改动文件**，约 750 行。核心变更：

**窗口标题**: `"eDAS-gh26.1.24"` → `"WFBG-7825 DAS"`

**标题栏文字**: `"分布式光纤传感系统（eDAS）"` → `"WFBG-7825 分布式光纤传感系统"`

**左面板参数区变更**：

移除的控件：
- DataRate ComboBox
- Rate2Phase ComboBox
- SpaceAvg SpinBox
- Merge SpinBox
- DiffOrder SpinBox
- rad Checkbox

修改的控件：
- CenterFreq: SpinBox → ComboBox (80MHz / 200MHz)
- Region 标签: "Region:" → "FBG Idx:"

新增的控件 (Peak Detection 组)：
```
Peak Detection Group
├── AmpBase: SpinBox (0-65535, default 2000)
├── FBG Interval: DoubleSpinBox (0.1-100.0m, default 5.0)
├── [Get Peak Info] Button (蓝色)
├── Save Peak Info: Checkbox
├── CH0 Peaks: Label (蓝色粗体)
├── CH1 Peaks: Label (橙色粗体)
└── Valid FBG: Label (绿色粗体)
```

**新增 `_on_get_peak_info()` 方法**：

寻峰按钮的独立功能，流程：
1. 收集参数并验证
2. 配置设备 (如非仿真模式)
3. 调用 `api.get_peak_info()` 获取寻峰结果
4. 调用 `api.get_valid_fbg_num()` 获取有效 FBG 数
5. 更新标签显示
6. 在 Plot 1 显示幅值波形和峰值标记
7. 可选保存寻峰信息到文件

**START 流程变更**：

```python
# 7821 流程:
# collect_params → validate → configure_device → start → create_thread

# 7825 流程:
# collect_params → validate → configure_device
#   → 如果未寻峰: 自动运行 get_peak_info
#   → get_valid_fbg_num
#   → allocate_buffers (使用 fbg_num_per_ch)
#   → start → create_thread (传入 fbg_num_per_ch)
```

**相位显示使用 fbg_num 语义**：
```python
# 7821:
point_num = self.params.basic.point_num_per_scan // self.params.phase_demod.merge_point_num

# 7825:
fbg_num = self._fbg_num_per_ch
```

**原始数据频谱采样率**：
```python
# 7821: sample_rate = 1e9 / self.params.upload.data_rate
# 7825: sample_rate = 1e9  # 固定 1GSps
```

**Monitor 绘图**：X 轴标签改为 "FBG Index"（而非 7821 的 "Position"）

**光纤长度显示**：
```python
# 7821: calculate_fiber_length(point_num, data_rate, data_source, rate2phase)
# 7825: calculate_fiber_length(point_num)  # 简化，固定 1GSps
```

**文件大小估算使用 fbg_num**：
```python
# 7821: frame_size = point_num // merge_points * channel_num * 4
# 7825: frame_size = fbg_num * channel_num * 4
```

**`_set_params_enabled()` 控件列表更新**：移除 data_rate_combo, rate2phase_combo 等，新增 amp_base_spin, fbg_interval_spin, get_peak_btn。

#### 3.3.9 `src/main.py` — 入口点

从 7821 复制并修改：
- 描述文字: `"PCIe-7821"` → `"WFBG-7825"`
- 日志文件名: `"pcie7821_*.log"` → `"logs/wfbg7825_*.log"`
- 应用名称: `"eDAS-gh26.1.24"` → `"WFBG-7825 DAS"`
- 窗口标题 (仿真): `"eDAS-gh26.1.24 [SIMULATION MODE]"` → `"WFBG-7825 DAS [SIMULATION MODE]"`

#### 3.3.10 `run.py` — 启动脚本

从 7821 复制，仅修改文件头注释中的产品名称。

---

## 四、验证测试

### 4.1 模块导入测试

逐个验证所有 Python 模块能否正常导入：

```bash
python -c "import sys; sys.path.insert(0,'src'); import config; print('OK')"
python -c "import sys; sys.path.insert(0,'src'); import logger; print('OK')"
python -c "import sys; sys.path.insert(0,'src'); import spectrum_analyzer; print('OK')"
python -c "import sys; sys.path.insert(0,'src'); import data_saver; print('OK')"
python -c "import sys; sys.path.insert(0,'src'); import wfbg7825_api; print('OK')"
python -c "import sys; sys.path.insert(0,'src'); import acquisition_thread; print('OK')"
python -c "import sys; sys.path.insert(0,'src'); import main_window; print('OK')"
```

**结果**: 全部 OK，无导入错误。

### 4.2 DLL 加载测试

```bash
python -c "import ctypes; dll = ctypes.CDLL('libs/wfbg7825_api.dll'); print('DLL loaded OK')"
```

**结果**: DLL 加载成功。

### 4.3 参数验证测试

```python
from config import validate_point_num, calculate_fiber_length

# 有效用例
assert validate_point_num(20480, 1)[0] == True
assert validate_point_num(20480, 2)[0] == True

# 无效用例
assert validate_point_num(262145, 1)[0] == False  # 超过单通道最大值
assert validate_point_num(131073, 2)[0] == False  # 超过双通道最大值
assert validate_point_num(1000, 1)[0] == False     # 未对齐 512
assert validate_point_num(20480, 4)[0] == False    # 不支持 4 通道

# 光纤长度
length = calculate_fiber_length(20480)
assert abs(length - 2.048) < 0.001  # 20480 * 0.1m / 1000 = 2.048 km
```

**结果**: 全部通过。

### 4.4 仿真模式 GUI 启动测试

```bash
timeout 8 python run.py --simulate
```

**输出**:
```
[    0.0 ms] [MainThread] [INFO] wfbg7825.main: ====...====
[    0.1 ms] [MainThread] [INFO] wfbg7825.main: WFBG-7825 DAS Acquisition Software Starting
[    0.1 ms] [MainThread] [INFO] wfbg7825.main: Simulation mode: True
[  203.7 ms] [MainThread] [INFO] wfbg7825.main: QApplication created
[  203.7 ms] [MainThread] [INFO] wfbg7825.main: Creating main window...
[  424.0 ms] [MainThread] [INFO] wfbg7825.gui:  MainWindow initializing (simulation_mode=True)
[ 1034.4 ms] [MainThread] [INFO] wfbg7825.gui:  MainWindow initialized
[ 1102.3 ms] [MainThread] [INFO] wfbg7825.main: Main window shown
[ 1102.4 ms] [MainThread] [INFO] wfbg7825.main: Entering event loop...
```

**结果**: GUI 成功启动，窗口初始化完成，进入事件循环。从初始化到窗口显示约 1.1 秒。

---

## 五、最终文件清单

```
E:/codes/das_fs_7825/7825GUIpy/
├── run.py                              # 快速启动脚本 (23 行)
├── libs/
│   └── wfbg7825_api.dll                # x64 DLL (24,576 字节)
├── src/
│   ├── __init__.py                     # 包标识 (6 行)
│   ├── main.py                         # 入口点 (98 行)
│   ├── config.py                       # 配置与参数 (170 行)
│   ├── wfbg7825_api.py                 # DLL 封装 (385 行)
│   ├── main_window.py                  # 主窗口 GUI (748 行)
│   ├── acquisition_thread.py           # 采集线程 (310 行)
│   ├── spectrum_analyzer.py            # FFT 分析 (133 行)
│   ├── data_saver.py                   # 异步保存 (209 行)
│   └── logger.py                       # 日志系统 (98 行)
├── logs/                               # 运行日志 (空)
├── output/                             # 数据输出 (空)
└── resources/
    └── logo.png                        # 公司 Logo
```

总代码量: 约 2,180 行 Python 代码。

---

## 六、已知限制与后续工作

### 6.1 已知限制

1. **bypass_point_num 对齐**: GUI SpinBox 设置了 step=4 引导用户输入 4 的倍数，但未在 validate 层面强制校验
2. **amplitude 数据类型**: API 返回的 amplitude 数据实际为 unsigned short (uint16)，但 `read_data` 使用 `short*`，在显示时类型不影响波形形态，但绝对值可能有差异
3. **寻峰后的重新寻峰**: 当参数变更后，应提示用户重新寻峰
4. **TimedFileSaver**: 未从 7821 移植（按需求无此需要）

### 6.2 后续可扩展功能

1. 添加音频播放功能（参考 C Demo 的 BX_Audio 模块）
2. 添加峰值信息的可视化编辑（手动调整寻峰结果）
3. 添加数据回放功能（读取已保存的 .bin 文件并显示）
4. 添加多语言支持
5. 添加参数预设保存/加载功能

---

## 七、技术栈

| 组件 | 技术 |
|------|------|
| GUI 框架 | PyQt5 |
| 绘图库 | pyqtgraph |
| 信号处理 | NumPy (FFT, 窗函数) |
| 硬件接口 | ctypes (DLL 调用) |
| 采集线程 | QThread + Qt 信号槽 |
| 文件保存 | threading.Thread + queue.Queue |
| 系统监控 | psutil |
| 日志 | Python logging |
| 配置管理 | dataclasses |
| 内存管理 | 自定义 AlignedBuffer (4096 对齐) |

---

## 八、依赖列表

```
PyQt5 >= 5.15
pyqtgraph >= 0.12
numpy >= 1.20
psutil >= 5.8
```

系统要求：Windows 7/8/10/11 (64-bit)，已安装 PCIe-WFBG-7825 驱动。
