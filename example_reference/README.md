# PCIe-7821 DAS Acquisition Software

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green.svg)](https://pypi.org/project/PyQt5/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)

A comprehensive PyQt5-based GUI application for real-time Distributed Acoustic Sensing (DAS) data acquisition and visualization using the PCIe-7821 acquisition card.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Development](#development)
- [API Reference](#api-reference)
- [Performance Optimization](#performance-optimization)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Overview

This application provides a complete solution for DAS data acquisition, real-time visualization, and storage. It interfaces with the PCIe-7821 acquisition card to capture phase data from distributed acoustic sensing systems and presents it through an intuitive GUI with advanced visualization capabilities.

### Key Capabilities

- **Real-time Data Acquisition**: High-speed data capture from PCIe-7821 hardware
- **Multi-domain Visualization**: Time-domain, frequency-domain, and time-space plotting
- **Advanced Signal Processing**: Real-time spectrum analysis with configurable parameters
- **Flexible Data Storage**: Frame-based file saving with compression and metadata
- **Performance Monitoring**: System resource monitoring and optimization tools
- **Simulation Mode**: Hardware-independent testing and development environment

## Features

### Data Acquisition
- **High-speed Sampling**: Up to 125 MHz sampling rate with PCIe-7821
- **Multi-channel Support**: Configurable channel count (1, 2, 4, 8, 16, 32)
- **Flexible Triggering**: Internal/external clock and trigger options
- **Buffer Management**: Optimized multi-level buffering for continuous acquisition

### Visualization
- **Time-domain Plots**: Real-time waveform display with downsampling
- **Spectrum Analysis**: FFT-based frequency domain visualization with PSD support
- **Time-space Plots**: 2D visualization for spatial-temporal phase analysis
- **Interactive Controls**: Zoom, pan, and measurement tools
- **Customizable Colormaps**: Multiple color schemes for enhanced data interpretation

### Data Processing
- **Real-time FFT**: Hardware-accelerated spectrum computation
- **Phase Demodulation**: Configurable phase unwrapping and calibration
- **Downsampling**: Intelligent data reduction for display optimization
- **Unit Conversion**: Automatic scaling between raw data and physical units

### Storage and Export
- **Frame-based Storage**: Efficient binary data format with metadata
- **Compression Support**: Optional data compression for storage optimization
- **Export Capabilities**: CSV, binary, and custom format export
- **Metadata Management**: Complete parameter and timestamp recording

## Architecture

### System Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   PCIe-7821     │    │  Acquisition    │    │   Main Window   │
│   Hardware      │───▶│     Thread      │───▶│      GUI        │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                               │                        │
                               ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Saver    │    │   Spectrum      │    │  Time-space     │
│     Thread      │    │   Analyzer      │    │   Plot Widget   │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Threading Model

The application uses a multi-threaded architecture to ensure responsive GUI performance and continuous data acquisition:

#### Thread Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MAIN THREAD (GUI)                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │    Main     │  │    Time     │  │ Time-Space  │  │   System    │    │
│  │   Window    │  │    Plot     │  │    Plot     │  │   Status    │    │
│  │             │  │   Widget    │  │   Widget    │  │   Timers    │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
│         │                │                │                │           │
│         │ Qt Signals     │ Qt Signals     │ Qt Signals     │           │
│         ▼                ▼                ▼                ▼           │
└─────────────────────────────────────────────────────────────────────────┘
          │
          │ Qt Signal-Slot Communication
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      ACQUISITION THREAD                                │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    QThread-based                                │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │   │
│  │  │   PCIe API  │  │   Dynamic   │  │     GUI     │            │   │
│  │  │ Interaction │  │   Polling   │  │ Throttling  │            │   │
│  │  │             │  │   Control   │  │  (20 FPS)   │            │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                       │
│                                │ Queue-based                           │
│                                ▼                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        DATA SAVER THREAD                               │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                   Background Thread                             │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │   │
│  │  │    Queue    │  │    File     │  │   Frame     │            │   │
│  │  │ Processing  │  │    I/O      │  │  Splitting  │            │   │
│  │  │             │  │  Operations │  │   Logic     │            │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Thread Specifications

##### 1. Main Thread (GUI Thread)
- **Purpose**: User interface management and application coordination
- **Components**:
  - `MainWindow`: Primary application window and control logic
  - `TimeSpacePlotWidget`: Advanced 2D visualization component
  - PyQtGraph widgets: Real-time plotting and spectrum displays
  - Qt timers: Status updates and system monitoring
- **Responsibilities**:
  - User interaction handling (button clicks, parameter changes)
  - GUI updates and plot rendering
  - Parameter validation and configuration management
  - Signal-slot coordination between components
- **Update Rate**: 60 FPS for GUI, 20 FPS max for data visualization
- **Thread Safety**: All GUI operations must occur in this thread

##### 2. Acquisition Thread (`AcquisitionThread`)
- **Purpose**: Hardware interface and continuous data capture
- **Implementation**: QThread-based with signal-slot communication
- **Key Features**:
  - **Dynamic Polling**: Adjusts polling interval (1-10ms) based on buffer usage
  - **GUI Throttling**: Limits signal emission to 20 FPS to prevent queue backup
  - **Pause/Resume**: QMutex + QWaitCondition for thread-safe state control
  - **Error Recovery**: Graceful handling of hardware communication failures
- **Data Types Handled**:
  - Raw IQ data (int16): Direct from ADC for maximum bandwidth
  - Phase data (int32): Demodulated phase information
  - Monitor data (uint32): System status and fiber end detection
- **Buffer Management**:
  - Hardware DMA buffer polling
  - Adaptive polling intervals based on fill ratio
  - Timeout protection (5-second maximum wait)
- **Signal Emissions**:
  - `data_ready(np.ndarray, int, int)`: Raw data with type and channel info
  - `phase_data_ready(np.ndarray, int)`: Processed phase data
  - `monitor_data_ready(np.ndarray, int)`: System monitoring data
  - `buffer_status(int, int)`: Buffer usage statistics
  - `error_occurred(str)`: Error notifications

##### 3. Data Saver Thread (`FrameBasedFileSaver`)
- **Purpose**: Asynchronous data storage without blocking acquisition
- **Implementation**: Python threading.Thread with queue-based communication
- **Architecture**:
  - **Producer-Consumer Pattern**: Acquisition thread queues data, saver thread writes
  - **Non-blocking Queue**: `queue.put_nowait()` drops data when full to prevent backpressure
  - **Frame-based File Splitting**: Automatic file creation every N frames
- **File Management**:
  - Filename format: `{seq}-eDAS-{rate}Hz-{points}pt-{timestamp}.{ms}.bin`
  - Example: `00001-eDAS-1000Hz-0162pt-20260126T014051.256.bin`
  - Default storage location: `D:/eDAS_DATA/`
  - Configurable frames per file (default: 10 frames)
- **Data Format**:
  - Binary format: 32-bit signed integers (int32)
  - No unit conversion applied (raw phase data preserved)
  - Metadata embedded in filename

##### 4. Spectrum Analysis (In-Thread Processing)
- **Purpose**: Real-time frequency domain analysis
- **Implementation**: Synchronous processing in main thread during data updates
- **Features**:
  - FFT-based spectrum computation
  - Multiple window functions (Hanning, Hamming, Blackman, Flat-top)
  - Power Spectral Density (PSD) calculation
  - Windowing correction factors for accurate measurements
- **Performance Optimization**:
  - Window function caching
  - Optimized NumPy FFT operations
  - Adaptive downsampling for display

### Data Flow Architecture

#### Overall Data Pipeline

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   PCIe-7821 │    │    DMA      │    │    API      │    │ Acquisition │
│  Hardware   │───▶│   Buffer    │───▶│  Interface  │───▶│   Thread    │
│             │    │             │    │             │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                                  │
                                                                  │ Qt Signals
                                                                  ▼
                   ┌─────────────────────────────────────────────────────┐
                   │                 MAIN THREAD                         │
                   │                                                     │
                   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
                   │  │    Data     │  │  Spectrum   │  │   Display   │ │
                   │  │ Processing  │  │  Analysis   │  │  Rendering  │ │
                   │  │             │  │             │  │             │ │
                   │  └─────────────┘  └─────────────┘  └─────────────┘ │
                   │         │                │                │       │
                   │         ▼                ▼                ▼       │
                   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
                   │  │ Time-Space  │  │ Time Domain │  │ Freq Domain │ │
                   │  │    Plot     │  │    Plot     │  │    Plot     │ │
                   │  │             │  │             │  │             │ │
                   │  └─────────────┘  └─────────────┘  └─────────────┘ │
                   └─────────────────────────────────────────────────────┘
                                      │
                                      │ Queue-based (non-blocking)
                                      ▼
                   ┌─────────────────────────────────────────────────────┐
                   │                SAVER THREAD                        │
                   │                                                     │
                   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
                   │  │    Data     │  │    File     │  │   Frame     │ │
                   │  │   Queue     │  │   Writer    │  │  Manager    │ │
                   │  │             │  │             │  │             │ │
                   │  └─────────────┘  └─────────────┘  └─────────────┘ │
                   │                            │                       │
                   │                            ▼                       │
                   │                  ┌─────────────┐                   │
                   │                  │    Disk     │                   │
                   │                  │   Storage   │                   │
                   │                  │             │                   │
                   │                  └─────────────┘                   │
                   └─────────────────────────────────────────────────────┘
```

#### Signal-Slot Communication Flow

The application uses Qt's signal-slot mechanism for thread-safe communication:

##### Acquisition Thread → Main Thread
```python
# Data signals (throttled to 20 FPS max)
data_ready(np.ndarray, int, int)        # Raw IQ data
phase_data_ready(np.ndarray, int)       # Demodulated phase data
monitor_data_ready(np.ndarray, int)     # System monitoring data

# Status signals
buffer_status(int, int)                 # Buffer usage statistics
error_occurred(str)                     # Error notifications
acquisition_started()                   # Acquisition start confirmation
acquisition_stopped()                   # Acquisition stop confirmation
```

##### Main Thread → Acquisition Thread
```python
# Control methods (thread-safe)
configure(AllParams)                    # Parameter configuration
start()                                 # Begin acquisition
stop()                                  # Stop acquisition
pause()                                 # Pause acquisition
resume()                                # Resume acquisition
```

##### GUI Internal Signals
```python
# Widget parameter changes
parametersChanged.connect(handler)      # Time-space plot parameters
pointCountChanged.connect(handler)      # Point count updates
plotStateChanged.connect(handler)       # Plot state changes

# User interface events
start_btn.clicked.connect(start_acq)    # Start button
stop_btn.clicked.connect(stop_acq)      # Stop button
combo.currentIndexChanged.connect(...)  # Parameter changes
```

#### Data Processing Pipeline

##### 1. Hardware Data Acquisition
- **Source**: PCIe-7821 acquisition card DMA buffer
- **Polling Strategy**: Dynamic interval adjustment (1-10ms)
  - High usage (>80%): 1ms polling for low latency
  - Low usage (<30%): 10ms polling for reduced CPU usage
- **Data Types**:
  - Raw mode: 16-bit signed integers (ADC samples)
  - Phase mode: 32-bit signed integers (demodulated phase)
- **Buffer Management**: Hardware buffer query → wait for sufficient data → bulk read

##### 2. Thread Communication
- **Mechanism**: Qt signals with automatic queuing and thread-safe delivery
- **Throttling**: Maximum 20 FPS emission rate to prevent Qt event queue backup
- **Data Packaging**: NumPy arrays passed by reference with metadata
- **Error Propagation**: Exception handling with error signal emission

##### 3. GUI Data Processing
- **Reception**: Signal handlers in main thread receive data arrays
- **Downsampling**: Intelligent reduction for display optimization
  - Time domain: Skip-based downsampling for waveform display
  - Time-space: 2D decimation with configurable factors
- **Unit Conversion**: Raw integers → physical units (radians, volts)
- **Buffer Management**: Circular buffers for continuous display

##### 4. Spectrum Analysis
- **Trigger**: Automatic on each data update in main thread
- **Window Functions**: Cached computation for performance
  - Hanning: General-purpose balanced window
  - Blackman: Excellent side-lobe suppression
  - Flat-top: Amplitude accuracy optimization
- **FFT Processing**: NumPy-based with proper scaling
- **PSD Calculation**: Power spectral density with noise bandwidth correction

##### 5. Asynchronous Storage
- **Queue Architecture**:
  - Producer: Main thread queues frame data
  - Consumer: Background thread writes to disk
  - Capacity: 200 frame buffer (configurable)
- **Storage Strategy**:
  - Non-blocking: Drops data when queue full to prevent acquisition stalls
  - Frame-based splitting: New file every N frames (default 10)
  - Binary format: Preserves raw integer data for maximum precision
- **File Management**:
  - Timestamped filenames with metadata
  - Automatic directory creation
  - Atomic file operations with proper cleanup

#### Performance Characteristics

##### Thread Performance Metrics
- **Acquisition Thread**:
  - Latency: 1-10ms polling intervals
  - Throughput: Up to 125 MHz sampling rate
  - CPU Usage: 5-15% on modern systems
- **Main Thread GUI**:
  - Update Rate: 60 FPS GUI, 20 FPS data visualization
  - Responsiveness: <50ms user interaction response
  - Memory Usage: Circular buffers prevent growth
- **Storage Thread**:
  - Write Speed: Limited by disk I/O (typically 100+ MB/s)
  - Queue Latency: <100ms typical
  - Buffer Overflow: Graceful degradation with data dropping

##### Memory Management
- **Acquisition Buffers**: Pre-allocated circular buffers
- **Display Buffers**: Fixed-size with automatic aging
- **Storage Queue**: Bounded queue with overflow protection
- **Total Memory**: Typically 50-200MB depending on configuration

##### Synchronization Mechanisms
- **Qt Signals**: Thread-safe communication between threads
- **QMutex**: Critical section protection for shared state
- **QWaitCondition**: Pause/resume coordination
- **Queue.Queue**: Python thread-safe queue for storage pipeline

## Installation

### Prerequisites

- Python 3.8 or higher
- Windows 10/11 (for PCIe-7821 driver support)
- PCIe-7821 acquisition card and drivers
- At least 8GB RAM (16GB recommended for high data rates)

### Dependencies

```bash
pip install PyQt5>=5.15.0
pip install numpy>=1.20.0
pip install pyqtgraph>=0.12.0
pip install psutil>=5.8.0
```

### Installation Steps

1. **Clone the repository**:
   ```bash
   git clone [repository-url]
   cd pcie7821_gui
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install PCIe-7821 drivers** (hardware mode only):
   - Follow manufacturer's driver installation guide
   - Verify card recognition in Device Manager

4. **Verify installation**:
   ```bash
   python run.py --simulate  # Test in simulation mode
   ```

## Usage

### Quick Start

#### Normal Mode (with Hardware)
```bash
python run.py
```

#### Simulation Mode (no hardware required)
```bash
python run.py --simulate
```

#### Debug Mode (detailed logging)
```bash
python run.py --debug --log debug.log
```

### Command Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--simulate` | Run without hardware | `python run.py --simulate` |
| `--debug` | Enable debug logging | `python run.py --debug` |
| `--log FILE` | Save log to file | `python run.py --log output.log` |

### GUI Operation

#### Main Interface Layout

```
┌─────────────────┬─────────────────────────────────────┐
│                 │                                     │
│  Parameters     │           Visualization             │
│   Panel         │             Tabs                    │
│                 │                                     │
│  • Basic        │  ┌─────────────────────────────────┐ │
│  • Upload       │  │        Time Plot Tab           │ │
│  • Demod        │  │  ┌─────────┬─────────┬────────┐ │ │
│  • Display      │  │  │  Time   │ Spectrum│Monitor │ │ │
│  • Save         │  │  │ Domain  │Analysis │ Plot   │ │ │
│                 │  │  └─────────┴─────────┴────────┘ │ │
│                 │  └─────────────────────────────────┘ │
│                 │  ┌─────────────────────────────────┐ │
│                 │  │     Time-Space Plot Tab        │ │
│                 │  │                                 │ │
│                 │  └─────────────────────────────────┘ │
└─────────────────┴─────────────────────────────────────┘
```

#### Parameter Configuration

1. **Basic Parameters**: Sampling rate, point count, scan parameters
2. **Upload Parameters**: Channel configuration and data source
3. **Demodulation Parameters**: Phase processing settings
4. **Display Parameters**: Visualization options and frame settings
5. **Save Parameters**: Storage location and format options

#### Data Visualization

##### Time Plot Tab
- **Time Domain**: Real-time waveform display
- **Spectrum Analysis**: FFT-based frequency domain visualization
- **Monitor Plot**: System status and fiber end detection

##### Time-Space Plot Tab
- **2D Visualization**: Spatial-temporal phase representation
- **Interactive Controls**: Distance range, time window, colormap selection
- **Performance Options**: Configurable downsampling for optimization

### Workflow Example

1. **Configure Parameters**:
   - Set sampling rate and point count
   - Select appropriate channels
   - Configure display options

2. **Start Acquisition**:
   - Click "Start" button
   - Monitor real-time data in visualization tabs
   - Adjust parameters as needed

3. **Data Analysis**:
   - Use spectrum analysis for frequency domain inspection
   - Monitor time-space plot for spatial events
   - Export data for further processing

4. **Data Storage**:
   - Enable data saving if desired
   - Configure storage location and format
   - Monitor storage status in GUI

## Project Structure

```
pcie7821_gui/
├── src/                          # Source code
│   ├── main.py                   # Application entry point
│   ├── main_window.py            # Main GUI window
│   ├── config.py                 # Configuration management
│   ├── acquisition_thread.py     # Data acquisition logic
│   ├── data_saver.py             # Data storage management
│   ├── spectrum_analyzer.py      # Signal processing
│   ├── time_space_plot.py        # Visualization widgets
│   ├── pcie7821_api.py          # Hardware interface
│   └── logger.py                 # Logging system
├── tests/                        # Test suite
│   ├── test_*.py                 # Unit tests
│   └── __init__.py
├── examples/                     # Usage examples
│   ├── spectrum_analysis_explanation.py
│   └── interactive_plots_guide.py
├── docs/                         # Documentation
├── run.py                        # Quick launcher
├── requirements.txt              # Python dependencies
└── README.md                     # This file
```

### Core Modules

#### `main_window.py`
- **Purpose**: Primary GUI interface and application coordination
- **Key Classes**: `MainWindow`
- **Responsibilities**: Parameter management, visualization coordination, user interaction

#### `acquisition_thread.py`
- **Purpose**: Hardware interface and data capture
- **Key Classes**: `AcquisitionThread`, `SimulatedAcquisitionThread`
- **Responsibilities**: PCIe-7821 communication, buffer management, error handling

#### `time_space_plot.py`
- **Purpose**: Advanced 2D visualization capabilities
- **Key Classes**: `TimeSpacePlotWidget`
- **Responsibilities**: Real-time 2D plotting, interactive controls, performance optimization

#### `spectrum_analyzer.py`
- **Purpose**: Real-time signal processing and analysis
- **Key Classes**: `RealTimeSpectrumAnalyzer`
- **Responsibilities**: FFT computation, PSD analysis, frequency domain processing

#### `data_saver.py`
- **Purpose**: Asynchronous data storage and export
- **Key Classes**: `FrameBasedFileSaver`
- **Responsibilities**: File I/O, data compression, metadata management

#### `config.py`
- **Purpose**: Centralized configuration management
- **Key Features**: Parameter validation, hardware constraints, option mappings

## Configuration

### Parameter Categories

#### Basic Parameters
```python
basic_params = {
    'sample_rate_hz': 125000000,        # ADC sampling rate
    'point_num_per_scan': 20000,        # Points per acquisition scan
    'scan_rate': 2000,                  # Scan repetition rate
    'pulse_width_ns': 100,              # Pulse width in nanoseconds
}
```

#### Upload Parameters
```python
upload_params = {
    'channel_num': 8,                   # Number of active channels
    'data_source': 'external',          # Data source selection
    'trigger_direction': 'rising',      # Trigger edge type
    'clock_source': 'internal',         # Clock source selection
}
```

#### Display Parameters
```python
display_params = {
    'frame_num': 1024,                  # Display frame count
    'spectrum_enabled': True,           # Enable spectrum display
    'psd_enabled': False,               # Enable PSD mode
    'rad_conversion': True,             # Convert to radians
}
```

### Performance Tuning

#### Buffer Configuration
```python
OPTIMIZED_BUFFER_SIZES = {
    'acquisition_buffer_frames': 100,   # Hardware interface buffer
    'processing_buffer_frames': 50,     # Signal processing buffer
    'storage_queue_frames': 200,        # Storage queue size
    'display_buffer_frames': 30,        # GUI display buffer
}
```

#### Polling Configuration
```python
POLLING_CONFIG = {
    'high_freq_interval_ms': 1,         # High-speed polling interval
    'low_freq_interval_ms': 10,         # Low-speed polling interval
    'buffer_threshold_high': 0.8,       # High-speed trigger threshold
    'buffer_threshold_low': 0.3,        # Low-speed trigger threshold
}
```

### Hardware Constraints

| Parameter | Minimum | Maximum | Unit |
|-----------|---------|---------|------|
| Sample Rate | 1 MHz | 125 MHz | Hz |
| Points per Scan | 1000 | 100000 | points |
| Scan Rate | 1 | 10000 | Hz |
| Channel Count | 1 | 32 | channels |

## Development

### Development Environment Setup

1. **Clone repository**:
   ```bash
   git clone [repository-url]
   cd pcie7821_gui
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   ```

3. **Install development dependencies**:
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Run tests**:
   ```bash
   python -m pytest tests/
   ```

### Code Style Guidelines

- **PEP 8**: Follow Python style guidelines
- **Type Hints**: Use type annotations for function signatures
- **Docstrings**: Google-style docstrings for all public methods
- **Error Handling**: Comprehensive exception handling with logging

### Testing

#### Unit Tests
```bash
python -m pytest tests/test_*.py -v
```

#### Integration Tests
```bash
python -m pytest tests/test_integration.py -v
```

#### Simulation Mode Testing
```bash
python run.py --simulate --debug
```

### Adding New Features

1. **Create Feature Branch**:
   ```bash
   git checkout -b feature/new-feature
   ```

2. **Implement Changes**:
   - Add necessary code in appropriate modules
   - Update configuration if needed
   - Add comprehensive tests

3. **Testing**:
   ```bash
   python -m pytest tests/
   python run.py --simulate  # Test in simulation mode
   ```

4. **Documentation**:
   - Update docstrings and comments
   - Update this README if needed
   - Add examples if applicable

### Performance Profiling

#### Memory Usage
```python
import psutil
import tracemalloc

tracemalloc.start()
# Run application code
current, peak = tracemalloc.get_traced_memory()
print(f"Memory: Current={current/1024/1024:.2f}MB, Peak={peak/1024/1024:.2f}MB")
```

#### CPU Profiling
```python
import cProfile
import pstats

pr = cProfile.Profile()
pr.enable()
# Run application code
pr.disable()
stats = pstats.Stats(pr).sort_stats('cumulative')
stats.print_stats(20)
```

## API Reference

### Main Window API

#### `MainWindow(simulation_mode=False)`
Primary application window class.

**Parameters:**
- `simulation_mode` (bool): Enable simulation mode for testing

**Methods:**
- `start_acquisition()`: Begin data acquisition
- `stop_acquisition()`: Stop data acquisition
- `load_configuration(file_path)`: Load parameters from file
- `save_configuration(file_path)`: Save current parameters

### Time-Space Plot API

#### `TimeSpacePlotWidget()`
Advanced 2D visualization widget.

**Methods:**
- `update_data(data)`: Update plot with new data array
- `get_parameters()`: Return current plot parameters
- `set_parameters(params)`: Apply new plot parameters
- `clear_data()`: Clear plot and reset buffers

**Signals:**
- `parametersChanged`: Emitted when plot parameters change
- `pointCountChanged(int)`: Emitted when point count changes

### Acquisition Thread API

#### `AcquisitionThread(params, simulation=False)`
Data acquisition and hardware interface.

**Parameters:**
- `params`: Configuration parameters
- `simulation` (bool): Use simulated data source

**Methods:**
- `start()`: Begin acquisition thread
- `stop()`: Stop acquisition gracefully
- `pause()`: Pause acquisition temporarily
- `resume()`: Resume paused acquisition

**Signals:**
- `dataReady(numpy.ndarray)`: New data available
- `errorOccurred(str)`: Error in acquisition
- `statusChanged(str)`: Status update message

### Configuration API

#### Parameter Validation
```python
from config import validate_point_num, validate_scan_rate

# Validate point count
valid, message = validate_point_num(point_num, channel_count)

# Validate scan rate
valid, message = validate_scan_rate(scan_rate, max_rate)
```

#### Hardware Constraints
```python
from config import CHANNEL_NUM_OPTIONS, DATA_RATE_OPTIONS

# Get valid channel options
channels = [opt[1] for opt in CHANNEL_NUM_OPTIONS]

# Get valid data rate options
rates = [opt[1] for opt in DATA_RATE_OPTIONS]
```

## Performance Optimization

### Memory Management

#### Buffer Optimization
- **Circular Buffers**: Prevent memory fragmentation
- **Pre-allocation**: Reduce garbage collection overhead
- **Shared Arrays**: Minimize memory copies between threads

#### Best Practices
```python
# Pre-allocate arrays
data_buffer = np.empty((buffer_size, point_count), dtype=np.int32)

# Use views instead of copies
data_view = data_buffer[start_idx:end_idx]

# Explicit memory management
del large_array
gc.collect()
```

### CPU Optimization

#### Threading Strategy
- **I/O Operations**: Separate thread for file operations
- **Data Processing**: Background thread for FFT and analysis
- **GUI Updates**: Rate-limited updates to prevent blocking

#### NumPy Optimization
```python
# Use optimized NumPy functions
result = np.fft.fft(data, n=fft_size)  # Hardware-accelerated

# Vectorized operations
processed = np.multiply(data, scaling_factor)  # Faster than loops

# In-place operations when possible
np.multiply(data, scaling_factor, out=data)  # Saves memory
```

### Display Optimization

#### Downsampling Strategy
```python
# Time domain downsampling
downsampled = data[::downsample_factor]

# Frequency domain decimation
spectrum = np.fft.fft(data)
decimated = spectrum[::decimation_factor]

# Adaptive downsampling based on zoom level
factor = int(np.ceil(data_length / display_width))
displayed = data[::factor]
```

#### Update Rate Control
```python
# Limit GUI update frequency
if time.time() - last_update > min_update_interval:
    self.plot_widget.setData(data)
    last_update = time.time()
```

## Troubleshooting

### Common Issues

#### Hardware Not Detected
**Problem**: PCIe-7821 card not recognized
**Solutions**:
1. Verify driver installation in Device Manager
2. Check card seating in PCIe slot
3. Run as administrator if needed
4. Use simulation mode for testing: `python run.py --simulate`

#### Memory Issues
**Problem**: Application consuming excessive memory
**Solutions**:
1. Reduce buffer sizes in configuration
2. Lower display frame count
3. Enable data compression
4. Close unused visualization tabs

#### Performance Problems
**Problem**: Slow data acquisition or display
**Solutions**:
1. Increase downsampling factors
2. Reduce spectrum analysis complexity
3. Lower acquisition rate temporarily
4. Check system resource usage

#### Data Corruption
**Problem**: Invalid or corrupted data readings
**Solutions**:
1. Verify hardware connections
2. Check sampling rate configuration
3. Ensure adequate power supply
4. Review trigger settings

### Error Codes

| Code | Message | Solution |
|------|---------|----------|
| E001 | Hardware initialization failed | Check drivers and connections |
| E002 | Buffer overflow detected | Reduce acquisition rate or increase buffers |
| E003 | Invalid parameter configuration | Review parameter constraints |
| E004 | File I/O error | Check disk space and permissions |
| E005 | Processing thread timeout | Reduce processing complexity |

### Debug Mode

Enable comprehensive logging:
```bash
python run.py --debug --log debug.log
```

Log levels and categories:
- `DEBUG`: Detailed execution flow
- `INFO`: General status messages
- `WARNING`: Non-critical issues
- `ERROR`: Critical errors requiring attention

### Performance Monitoring

#### Real-time Metrics
- CPU usage per thread
- Memory consumption
- Buffer fill levels
- Data acquisition rate
- Processing latency

#### Log Analysis
```bash
# Search for errors
grep "ERROR" debug.log

# Monitor buffer status
grep "buffer" debug.log | tail -20

# Check performance metrics
grep "performance" debug.log
```

## Contributing

### Development Workflow

1. **Fork Repository**: Create personal fork of main repository
2. **Feature Branch**: Create feature branch from main
3. **Development**: Implement changes with tests
4. **Testing**: Verify functionality in both modes
5. **Documentation**: Update relevant documentation
6. **Pull Request**: Submit PR with clear description

### Code Review Process

- **Automated Testing**: All tests must pass
- **Code Style**: PEP 8 compliance required
- **Performance**: No significant performance regression
- **Documentation**: Public API changes must be documented
- **Simulation**: Changes must work in simulation mode

### Coding Standards

#### Documentation
```python
def process_data(data: np.ndarray, config: dict) -> np.ndarray:
    """
    Process raw acquisition data with specified configuration.

    Args:
        data: Raw data array (frames x points)
        config: Processing configuration dictionary

    Returns:
        Processed data array with same shape as input

    Raises:
        ValueError: If data shape incompatible with configuration
        ProcessingError: If processing parameters invalid
    """
    pass
```

#### Error Handling
```python
try:
    result = risky_operation()
except SpecificException as e:
    log.error(f"Operation failed: {e}")
    raise ProcessingError(f"Cannot process data: {e}") from e
```

#### Threading
```python
import threading
import queue

class SafeDataProcessor:
    def __init__(self):
        self._data_queue = queue.Queue()
        self._processing_lock = threading.Lock()

    def process_safely(self, data):
        with self._processing_lock:
            # Thread-safe processing
            pass
```

---

## License

This software is proprietary and confidential. Unauthorized copying, modification, distribution, or use is strictly prohibited.

## Contact

For technical support or development questions:
- Email: [support@example.com]
- Documentation: [docs-url]
- Issue Tracker: [issues-url]

---

**Version**: 1.0.0
**Last Updated**: 2024
**Maintainers**: eDAS Development Team