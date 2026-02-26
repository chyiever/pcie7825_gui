"""
WFBG-7825 DAS Configuration Module

Configuration management for the WFBG-7825 Weak Fiber Bragg Grating DAS system.
Defines parameters, enumerations, validation, and hardware constraints.

Key differences from PCIe-7821:
- Channels: 1/2 only (no 4-channel)
- Data sources: raw(0), amplitude(1), phase(2) (no I/Q, arctan)
- No data_rate control (fixed 1GSps)
- Phase demod: only polarization and detrend (no rate2phase, avg, merge, diff)
- FBG peak detection parameters (NEW)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from enum import IntEnum


# ----- ENUMERATION DEFINITIONS -----

class ClockSource(IntEnum):
    INTERNAL = 0
    EXTERNAL = 1


class TriggerDirection(IntEnum):
    INPUT = 0
    OUTPUT = 1


class DataSource(IntEnum):
    """Data processing pipeline selection for WFBG-7825."""
    RAW = 0         # Raw backscattered optical data
    AMPLITUDE = 1   # sqrt(I^2 + Q^2) amplitude data
    PHASE = 2       # Phase-demodulated data


class DisplayMode(IntEnum):
    TIME = 0   # Multiple frames overlay
    SPACE = 1  # Single FBG position over time


# ----- PARAMETER DATA STRUCTURES -----

@dataclass
class BasicParams:
    """Core acquisition hardware parameters."""
    clk_src: int = ClockSource.INTERNAL
    trig_dir: int = TriggerDirection.OUTPUT
    scan_rate: int = 2000
    pulse_width_ns: int = 60
    point_num_per_scan: int = 10240
    bypass_point_num: int = 60
    center_freq_mhz: int = 200


@dataclass
class UploadParams:
    """Data upload configuration. No data_rate field (fixed 1GSps)."""
    channel_num: int = 1
    data_source: int = DataSource.PHASE


@dataclass
class PhaseDemodParams:
    """Phase demodulation parameters. Only polarization and detrend for 7825."""
    polarization_diversity: bool = False
    detrend_bw: float = 0.5


@dataclass
class PeakDetectionParams:
    """FBG peak detection parameters (NEW for 7825)."""
    amp_base_line: int = 3000
    fbg_interval_m: float = 5.0


@dataclass
class TimeSpaceParams:
    """
    Time-Space plot configuration parameters.

    Controls the 2D time-space plot visualization including rolling window
    behavior, spatial range selection, downsampling, and colormap settings.

    Attributes:
        window_frames: Number of frames to keep in rolling window (temporal dimension)
        distance_range_start: Starting FBG index for display (adapted for WFBG-7825)
        distance_range_end: Ending FBG index for display (adapted for WFBG-7825)
        time_downsample: Time dimension downsampling factor (1=no downsampling)
        space_downsample: Space dimension downsampling factor (1=no downsampling)
        colormap_type: Colormap type for 2D visualization
        vmin: Minimum value for color mapping
        vmax: Maximum value for color mapping
    """
    window_frames: int = 1              # Rolling window size in frames
    distance_range_start: int = 40      # Start index for FBG range
    distance_range_end: int = 100       # End index for FBG range
    time_downsample: int = 10           # Time downsampling factor
    space_downsample: int = 1           # Space downsampling factor
    colormap_type: str = "hsv"          # PyQtGraph colormap name
    vmin: float = -0.1                 # Color range minimum (for phase data)
    vmax: float = 0.1                  # Color range maximum (for phase data)


@dataclass
class DisplayParams:
    """Real-time display configuration."""
    mode: int = DisplayMode.TIME
    region_index: int = 0       # FBG index for SPACE mode
    frame_num: int = 1000
    spectrum_enable: bool = False
    psd_enable: bool = False
    rad_enable: bool = False    # Convert phase data to radians for display (storage unaffected)


@dataclass
class SaveParams:
    """Data storage configuration."""
    enable: bool = False
    path: str = "D:/WFBG7825_DATA"
    file_prefix: str = ""
    frames_per_file: int = 10


@dataclass
class AllParams:
    """Master parameter container."""
    basic: BasicParams = field(default_factory=BasicParams)
    upload: UploadParams = field(default_factory=UploadParams)
    phase_demod: PhaseDemodParams = field(default_factory=PhaseDemodParams)
    peak_detection: PeakDetectionParams = field(default_factory=PeakDetectionParams)
    time_space: TimeSpaceParams = field(default_factory=TimeSpaceParams)
    display: DisplayParams = field(default_factory=DisplayParams)
    save: SaveParams = field(default_factory=SaveParams)


# ----- GUI OPTION MAPPINGS -----

CHANNEL_NUM_OPTIONS: List[Tuple[str, int]] = [
    ("1", 1),
    ("2", 2),
]

DATA_SOURCE_OPTIONS: List[Tuple[str, int]] = [
    ("Raw", DataSource.RAW),
    ("\u221a(I\u00b2+Q\u00b2)", DataSource.AMPLITUDE),
    ("Phase", DataSource.PHASE),
]

CENTER_FREQ_OPTIONS: List[Tuple[str, int]] = [
    ("80 MHz", 80),
    ("200 MHz", 200),
]


# ----- HARDWARE CONSTRAINTS -----

MAX_POINT_NUM_1CH = 262144    # Single channel max
MAX_POINT_NUM_2CH = 131072    # Dual channel max

POINT_NUM_ALIGN_1CH = 512
POINT_NUM_ALIGN_2CH = 256

DMA_ALIGNMENT = 4096

MAX_FBG_PER_PHASE_DEM = 16384  # Max points entering phase_dem unit


# ----- ERROR CODE DEFINITIONS -----

ERROR_CODES: Dict[int, str] = {
    0: "Success",
    -1: "Device open failed / operation failed",
    -2: "Invalid parameter",
    -3: "Buffer overflow",
    -4: "Device not started",
    -5: "DMA error",
}


def get_error_message(code: int) -> str:
    """Retrieve human-readable error message for API error codes."""
    return ERROR_CODES.get(code, f"Unknown error ({code})")


# ----- VALIDATION FUNCTIONS -----

def validate_point_num(point_num: int, channel_num: int) -> Tuple[bool, str]:
    """Validate point_num_per_scan against channel-specific constraints."""
    if channel_num == 1:
        if point_num > MAX_POINT_NUM_1CH:
            return False, f"Single channel: point_num must be <= {MAX_POINT_NUM_1CH}"
        if point_num % POINT_NUM_ALIGN_1CH != 0:
            return False, f"Single channel: point_num must be multiple of {POINT_NUM_ALIGN_1CH}"
    elif channel_num == 2:
        if point_num > MAX_POINT_NUM_2CH:
            return False, f"Dual channel: point_num must be <= {MAX_POINT_NUM_2CH}"
        if point_num % POINT_NUM_ALIGN_2CH != 0:
            return False, f"Dual channel: point_num must be multiple of {POINT_NUM_ALIGN_2CH}"
    else:
        return False, f"Invalid channel_num: {channel_num} (must be 1 or 2)"

    return True, ""


def calculate_fiber_length(point_num: int) -> float:
    """Calculate equivalent fiber length. Fixed 1GSps, 0.1m per sample point."""
    return point_num * 0.1 / 1000.0  # km


def calculate_data_rate_mbps(scan_rate: int, point_num: int, channel_num: int) -> float:
    """Calculate sustained data rate in MB/s."""
    return scan_rate * point_num * 2 * channel_num / 1024.0 / 1024.0


# ----- PERFORMANCE OPTIMIZATION CONSTANTS -----

OPTIMIZED_BUFFER_SIZES = {
    'hardware_buffer_frames': 50,
    'signal_queue_frames': 20,
    'storage_queue_frames': 200,
    'display_buffer_frames': 30,
}

POLLING_CONFIG = {
    'high_freq_interval_ms': 1,
    'low_freq_interval_ms': 10,
    'buffer_threshold_high': 0.8,
    'buffer_threshold_low': 0.3,
}

MONITOR_UPDATE_INTERVALS = {
    'buffer_status_ms': 500,
    'system_status_s': 10,
    'performance_log_s': 30,
}

# ----- RAW DATA OPTIMIZATION CONSTANTS -----

RAW_DATA_CONFIG = {
    'gui_frame_limit': 1,               # 仅传输前1帧给GUI (保持)
    'time_domain_update_s': 3,        # 时域图更新间隔(秒) (1.0→1.5，减少负担)
    'fft_update_s': 5.0,               # FFT更新间隔(秒) (3.0→5.0，减少计算)
    'frame_averaging': False,           # 禁用4帧平均 (保持)
    'max_gui_update_fps':1,        # GUI最大更新频率(FPS) (1.0→0.66)
}

# ----- RAW数据按需采样配置 -----
RAW_SAMPLING_CONFIG = {
    'time_domain_interval_s': 1.0,     # 时域图采样间隔：每1秒采样一次
    'time_domain_frames': 4,           # 时域图帧数：读取4帧做平均
    'fft_interval_s': 5.0,             # FFT采样间隔：每5秒采样一次（仅当spectrum启用时）
    'fft_frames': 1,                   # FFT帧数：读取1帧计算FFT
}
