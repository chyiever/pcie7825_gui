# WFBG-7825 DAS Python GUI

基于 `PyQt5 + pyqtgraph` 开发的 PCIe-WFBG-7825 分布式光纤传感上位机软件，提供设备参数配置、峰值检测、实时波形显示、频谱分析、时空图显示、数据保存和日志记录等能力。

## 主要功能

- 采集参数配置
  - 时钟源、触发方向、扫描率、脉宽、采样点数、旁路点数、中心频率
- 数据源切换
  - `Raw`
  - `Amplitude`
  - `Phase`
- FBG 峰值检测
  - 获取 CH0/CH1 峰值信息
  - 获取有效 FBG 数量
  - 支持保存峰值结果文件
- 实时绘图
  - 时域曲线
  - FFT 频谱
  - Monitor 曲线
  - Time-Space 二维图
- 数据保存
  - 采集数据分块写入本地文件
  - 支持每文件帧数和下采样配置
- 仿真模式
  - 在无硬件条件下调试界面和绘图逻辑

## 项目结构

```text
pcie7825_gui/
├── build_exe.py
├── run.py
├── README.md
├── last_params.json
├── docs/
├── libs/
│   └── wfbg7825_api.dll
├── logs/
├── resources/
│   └── logo.png
├── src/
│   ├── acquisition_thread.py
│   ├── config.py
│   ├── fft_worker.py
│   ├── logger.py
│   ├── main.py
│   ├── main_window.py
│   ├── spectrum_analyzer.py
│   ├── time_space_plot.py
│   ├── wfbg7825_api.py
│   └── storage/
└── tests/
```

## 运行方式

### 环境要求

- Windows 64 位
- Python 3.8+
- 已安装 WFBG-7825 相关驱动和 DLL（真实硬件模式）

### 安装依赖

```bash
pip install PyQt5 pyqtgraph numpy psutil pyinstaller
```

### 启动

```bash
python run.py
```

### 仿真模式

```bash
python run.py --simulate
```

### 调试日志

```bash
python run.py --debug
```

### 自定义日志文件路径

```bash
python run.py --log custom.log
```

## 日志功能

程序启动后会自动在本地创建 `logs/` 目录，并自动写入日志文件，无需手工指定。

默认日志规则如下：

- 日志目录：项目根目录下的 `logs/`
- 日志文件名格式：`YYYY-MM-DD-HH-MM-log.txt`
- 默认每跨一天自动切换到新的日志文件
- 控制台日志和文件日志同时保留
- 若通过 `--log` 指定路径，则使用用户自定义路径

当前实现位于：

- `src/logger.py`
- `src/main.py`

## 参数自动保存功能

程序已实现本地参数自动保存与自动恢复，使用文件：

```text
last_params.json
```

行为如下：

- 启动窗口时自动尝试加载上一次保存的参数
- 点击 `Get Peak Info` 前会自动保存当前参数
- 点击 `START` 前会自动保存当前参数
- 关闭窗口时会再次保存当前参数

自动保存内容包括：

- 基础采集参数
- 上传参数
- 解调参数
- 峰值检测参数
- 显示参数
- 时空图参数
- 数据保存参数

相关实现位于：

- `src/main_window.py`

## UI 设计说明

界面整体采用左右分栏结构：

- 左侧为参数与控制面板
- 右侧为实时绘图与状态显示区域

UI 设计重点如下：

- 顶部 Header 显示 Logo 和系统标题
- 左侧集中放置采集参数、峰值检测、显示配置、数据保存等控件
- 右侧集中放置波形图、频谱图、监测图和时空图
- 底部状态栏显示设备连接状态、数据率、光纤长度等信息
- 支持仿真模式和真实硬件模式共用同一界面

为适应高分辨率屏幕，程序在入口中启用了高 DPI 支持。

## 绘图更新机制

当前绘图系统围绕实时性和交互性做了专门处理，主要包括：

- 使用 `pyqtgraph` 实现高性能实时绘图
- 通过采集线程和 GUI 线程分离，降低界面卡顿
- 对 Raw 数据显示采用按需刷新和频率限制
- 频谱绘图通过独立 FFT 工作线程异步计算
- Monitor 与 Time-Space 图按各自逻辑独立更新
- 绘图支持缩放、滚轮缩放、右键恢复全视图

当前已实现的交互与优化包括：

- 矩形框选缩放
- `Shift + 左键拖动` 水平平移
- 右键 `View All` 恢复视图
- 原始数据时域图和 FFT 图分开节流更新
- 时空图支持滚动窗口显示

相关实现主要位于：

- `src/main_window.py`
- `src/fft_worker.py`
- `src/time_space_plot.py`
- `src/spectrum_analyzer.py`
- `src/acquisition_thread.py`

## 数据保存

程序支持将采集数据保存到本地文件。

可配置项包括：

- 是否启用保存
- 保存路径
- 每个文件的帧数
- 下采样因子

保存逻辑位于：

- `src/storage/`

## 打包

项目提供了 `build_exe.py` 用于生成单文件 `exe`：

```bash
python build_exe.py
```

默认输出：

```text
dist/eDASread.exe
```

打包后程序可在未安装 Python 的 Windows 环境中运行。

## 关键源码说明

- `run.py`
  - 项目启动脚本
- `src/main.py`
  - 应用入口、命令行参数解析、日志初始化、高 DPI 配置
- `src/logger.py`
  - 日志系统、默认本地日志文件、按天切换
- `src/main_window.py`
  - 主界面、参数收集、参数自动保存、绘图联动、应用生命周期
- `src/wfbg7825_api.py`
  - 硬件 DLL 封装
- `src/acquisition_thread.py`
  - 数据采集线程
- `src/fft_worker.py`
  - FFT 异步计算线程
- `src/time_space_plot.py`
  - 时空图显示组件
- `src/storage/`
  - 数据保存模型、命名、写入与管理

## 常用命令

```bash
python run.py
python run.py --simulate
python run.py --debug
python run.py --log custom.log
python build_exe.py
```
