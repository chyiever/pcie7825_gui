# WFBG-7825 DAS Python GUI

PCIe-WFBG-7825 弱光纤光栅阵列分布式光纤传感系统上位机软件。

基于 PyQt5 + pyqtgraph 构建，提供实时波形显示、FFT 频谱分析、FBG 自动寻峰、数据采集与保存等功能。

---

## 快速开始

### 环境要求

- **操作系统**: Windows 7/8/10/11 (64-bit)
- **Python**: 3.8+
- **硬件**: PCIe-WFBG-7825 采集卡（仿真模式无需硬件）

### 安装依赖

```bash
pip install PyQt5 pyqtgraph numpy psutil
```

### 运行

```bash
# 正常模式（需要硬件）
python run.py

# 仿真模式（无需硬件，用于界面测试）
python run.py --simulate

# 调试模式 + 日志输出
python run.py --debug --log ""

# 自定义日志文件
python run.py -s -d -l debug.log
```

### 命令行参数

| 参数 | 缩写 | 说明 |
|------|------|------|
| `--simulate` | `-s` | 仿真模式，生成随机数据，无需硬件 |
| `--debug` | `-d` | 启用 DEBUG 级别日志 |
| `--log FILE` | `-l` | 指定日志文件路径，空字符串自动生成带时间戳的文件名 |

---

## 项目结构

```
7825GUIpy/
├── run.py                      # 启动脚本
├── README.md                   # 项目说明
├── devlog.md                   # 开发日志
├── libs/
│   └── wfbg7825_api.dll        # 硬件驱动 DLL (x64)
├── src/
│   ├── __init__.py             # 包标识
│   ├── main.py                 # 应用入口（argparse, 高DPI, 日志初始化）
│   ├── config.py               # 参数定义、枚举、验证、硬件约束
│   ├── wfbg7825_api.py         # DLL ctypes 封装（18个API函数）
│   ├── main_window.py          # PyQt5 主窗口（参数面板 + 绘图面板）
│   ├── acquisition_thread.py   # QThread 数据采集线程
│   ├── spectrum_analyzer.py    # FFT 频谱分析（窗函数、PSD）
│   ├── data_saver.py           # 异步数据保存（帧分文件）
│   └── logger.py               # 集中日志系统
├── logs/                       # 运行日志输出
├── output/                     # 数据输出
└── resources/
    └── logo.png                # 公司 Logo
```

---

## 功能概述

### 界面布局

```
┌─────────────────────────────────────────────────────┐
│  [Logo]   WFBG-7825 分布式光纤传感系统               │
├──────────────┬──────────────────────────────────────┤
│ Basic Params │  Plot 1: 时域/相位数据                │
│  Clock/Trig  │                                      │
│  ScanRate    ├──────────────────────────────────────┤
│  Points      │  Plot 2: FFT 频谱                    │
│              │                                      │
│ Upload Params├──────────────────────────────────────┤
│  Source/Ch   │  Plot 3: Monitor (FBG幅值)           │
│              │                                      │
│ Phase Demod  ├──────────────────────────────────────┤
│  Polar/Detr  │  Status: HW Buffer | STO Queue |     │
│              │  CPU | Disk | Poll | Frames | Save   │
│ Peak Detect  │                                      │
│  AmpBase     │                                      │
│  Interval    │                                      │
│  [GetPeak]   │                                      │
│  CH0/CH1/FBG │                                      │
│              │                                      │
│ Display Ctrl │                                      │
│  Mode/FBGIdx │                                      │
│  Frames/FFT  │                                      │
│              │                                      │
│ Data Save    │                                      │
│  Path/Frames │                                      │
│              │                                      │
│ [START][STOP]│                                      │
└──────────────┴──────────────────────────────────────┘
│  Device: Connected | Data Rate: 78.1 MB/s | Fiber: 2.05 km │
└─────────────────────────────────────────────────────────────┘
```

### 参数说明

#### Basic Parameters

| 参数 | 范围 | 默认值 | 说明 |
|------|------|--------|------|
| Clock | Int / Ext | Internal | 时钟源选择 |
| Trigger | In / Out | Output | 触发方向 |
| Scan Rate | 1-100000 Hz | 2000 | 脉冲重复频率 |
| Pulse Width | 4-1000 ns (步长4) | 100 | 触发脉冲高电平时间 |
| Points | 512-262144 (步长512) | 20480 | 每脉冲每通道采样点数 |
| Bypass | 0-65535 (步长4) | 60 | 延时采样点数 |
| Center Freq | 80 / 200 MHz | 200 | AOM 调制频率 |

#### Upload Parameters

| 参数 | 选项 | 默认值 | 说明 |
|------|------|--------|------|
| Source | Raw / Amplitude / Phase | Phase | 上传数据源 |
| Channels | 1 / 2 | 1 | 上传通道数 |

#### Phase Demod Parameters

| 参数 | 范围 | 默认值 | 说明 |
|------|------|--------|------|
| Polarization | On / Off | Off | 偏振分集（使能时通道数必须为1） |
| Detrend BW | 0-10000 Hz | 0.5 | 去趋势滤波器带宽（0=禁用） |

#### Peak Detection (WFBG-7825 专有)

| 参数 | 范围 | 默认值 | 说明 |
|------|------|--------|------|
| Amp Base | 0-65535 | 2000 | 幅度阈值，低于此值视为噪声 |
| FBG Interval | 0.1-100 m | 5.0 | 光栅间距 |

### 操作流程

1. **连接设备**: 启动程序后自动打开设备（仿真模式跳过）
2. **设置参数**: 在左侧面板配置采集参数
3. **寻峰** (可选): 点击 "Get Peak Info" 按钮预览 FBG 峰值分布
4. **启动采集**: 点击 "START"（如未寻峰，会自动执行寻峰）
5. **实时观测**: 右侧面板实时显示波形、频谱、监测数据
6. **数据保存**: 勾选 "Enable" 并设置路径，数据自动保存为 .bin 文件
7. **停止采集**: 点击 "STOP"

### 数据保存格式

保存文件为原始二进制格式：
- **相位数据**: int32 (4 字节/点)，定点数 32767 = +pi, -32768 = -pi
- **原始数据**: int16 (2 字节/点)
- **文件名**: `{序号}-wfbg7825-{扫描率}Hz-{点数}pt-{时间戳}.bin`
- **示例**: `00001-wfbg7825-2000Hz-0410pt-20260215T143052.256.bin`

### 显示模式

| 模式 | 说明 |
|------|------|
| Time | 叠加显示多帧数据（相位/原始） |
| Space | 提取单个 FBG 位置的时间序列 |
| Spectrum | FFT 功率谱 (dB) |
| PSD | 功率谱密度 (dB/Hz) |

---

## 硬件约束

| 参数 | 单通道 | 双通道 |
|------|--------|--------|
| 最大采样点数 | 262144 | 131072 |
| 点数对齐要求 | 512 的整数倍 | 256 的整数倍 |
| Phase_dem 最大输入点数 | 16384 | 16384 |
| DMA 缓冲对齐 | 4096 字节 | 4096 字节 |

---

## API 调用流程

```
wfbg7825_open()
  ├── wfbg7825_set_clk_src()
  ├── wfbg7825_set_trig_param(trig_dir, scan_rate, pulse_width)
  ├── wfbg7825_set_origin_point_num_per_scan()
  ├── wfbg7825_set_bypass_point_num()
  ├── wfbg7825_set_upload_data_param(ch_num, data_src)
  ├── wfbg7825_set_center_freq()
  ├── wfbg7825_set_phase_dem_param(polar_en, detrend_bw)
  ├── wfbg7825_get_peak_info()        ← 必须在 start 之前
  ├── wfbg7825_get_valid_fbg_num()    ← 必须在 start 之前
  ├── wfbg7825_start()
  │     ├── wfbg7825_point_num_per_ch_in_buf_query()
  │     ├── wfbg7825_read_data()          ← raw/amplitude
  │     └── wfbg7825_read_phase_data()    ← phase
  │         + wfbg7825_read_monitor_data()
  ├── wfbg7825_stop()
  └── wfbg7825_close()
```

---

## 依赖

| 包 | 最低版本 | 用途 |
|---|---------|------|
| PyQt5 | 5.15 | GUI 框架 |
| pyqtgraph | 0.12 | 高性能实时绘图 |
| numpy | 1.20 | 数值计算、FFT |
| psutil | 5.8 | CPU/磁盘监控 |

---

## 与 PCIe-7821 的主要区别

| 特性 | 7821 | 7825 |
|------|------|------|
| 定位 | 通用 DAS | WFBG 阵列专用 |
| 通道数 | 1/2/4 | 1/2 |
| 采样率 | 可变 (1-32ns) | 固定 1GSps |
| 数据源 | raw, I/Q, arctan, phase | raw, amplitude, phase |
| 触发设置 | 3 个独立函数 | 1 个组合函数 |
| 相位参数 | 6 个 | 2 个 (polar, detrend) |
| FBG 寻峰 | 无 | 内置自动寻峰 |
| 启动前提 | 直接启动 | 必须先寻峰 |
| 相位数据大小 | point_num / merge | fbg_num (寻峰决定) |
| Monitor 读取 | 无参数 | 需要 fbg_num 参数 |

---

## 许可

内部使用。
