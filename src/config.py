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
    pulse_width_ns: int = 100
    point_num_per_scan: int = 20480
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
    amp_base_line: int = 2000
    fbg_interval_m: float = 5.0


@dataclass
class DisplayParams:
    """Real-time display configuration."""
    mode: int = DisplayMode.TIME
    region_index: int = 0       # FBG index for SPACE mode
    frame_num: int = 1024
    spectrum_enable: bool = True
    psd_enable: bool = False
    # No rad_enable - 7825 phase is already calibrated


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
