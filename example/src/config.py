"""
PCIe-7821 DAS Configuration Module

This module provides comprehensive configuration management for the PCIe-7821
Distributed Acoustic Sensing (DAS) acquisition system. It defines all system
parameters, data structures, validation functions, and configuration mappings
used throughout the application.

Key Features:
- Centralized parameter management with dataclass structures
- Hardware constraint definitions and validation
- Option mappings for GUI combo boxes
- Error code definitions and lookup
- Performance optimization constants

Usage:
    from config import AllParams, validate_point_num

    params = AllParams()
    valid, msg = validate_point_num(params.basic.point_num_per_scan,
                                   params.upload.channel_num)

Author: PCIe-7821 Development Team
Last Modified: [Current Date]
Version: 1.0.0

Note: Future modifications should maintain backward compatibility with
      existing parameter structures and validation logic.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from enum import IntEnum


# ----- ENUMERATION DEFINITIONS -----
# Hardware clock source options for timing synchronization

class ClockSource(IntEnum):
    """
    Clock source enumeration for PCIe-7821 timing control.

    INTERNAL: Use onboard crystal oscillator (default)
    EXTERNAL: Use external reference clock input

    Note: External clock requires proper signal conditioning
    """
    INTERNAL = 0
    EXTERNAL = 1


class TriggerDirection(IntEnum):
    """
    Trigger signal direction control.

    INPUT: Accept external trigger signals
    OUTPUT: Generate trigger output for synchronization

    Usage: Typically OUTPUT for master mode, INPUT for slave mode
    """
    INPUT = 0
    OUTPUT = 1


class DataSource(IntEnum):
    """
    Data processing pipeline selection.

    Defines which stage of signal processing to upload to host:
    - raw: Raw backscattered optical data (ADC output)
    - I_Q: In-phase/Quadrature demodulated signals
    - arc: Arctangent phase calculation arctan(Q/I)
    - PHASE: Final phase-demodulated DAS data (recommended)

    Note: PHASE provides best SNR and processing efficiency
    """
    raw = 0     # Raw scattered light data from ADC
    I_Q = 2     # I/Q demodulated signals
    arc = 3     # Arctan phase calculation
    PHASE = 4   # Phase-demodulated data (default)


class DisplayMode(IntEnum):
    """
    Waveform display mode selection.

    TIME: Show multiple frames overlaid (temporal analysis)
    SPACE: Show single spatial position over time (position analysis)
    TIME_SPACE: Show 2D time-space plot with rolling window (advanced analysis)

    Usage: TIME for overall signal inspection, SPACE for specific location monitoring,
           TIME_SPACE for spatiotemporal pattern analysis
    """
    TIME = 0       # Time domain display (multiple frames overlay)
    SPACE = 1      # Space domain display (single region over time)
    TIME_SPACE = 2 # Time-space 2D plot with rolling window


# ----- PARAMETER DATA STRUCTURES -----
# Organized parameter groups using dataclasses for type safety and defaults

@dataclass
class BasicParams:
    """
    Core acquisition hardware parameters.

    These parameters directly control the PCIe-7821 FPGA acquisition engine.
    Changes require hardware reconfiguration and may affect data continuity.

    Attributes:
        clk_src: Clock source selection (internal/external)
        trig_dir: Trigger direction (input/output)
        scan_rate: Laser scan repetition rate in Hz (1-100000)
        pulse_width_ns: Laser pulse width in nanoseconds (10-1000)
        point_num_per_scan: Spatial sampling points per scan (512-262144)
        bypass_point_num: Initial points to skip (dead zone compensation)
        center_freq_mhz: RF center frequency in MHz (50-500)

    Validation: Use validate_point_num() before applying changes
    """
    clk_src: int = ClockSource.INTERNAL
    trig_dir: int = TriggerDirection.OUTPUT
    scan_rate: int = 2000                    # Hz - typical range 1000-5000
    pulse_width_ns: int = 100                # ns - affects spatial resolution
    point_num_per_scan: int = 20480          # Must align with channel constraints
    bypass_point_num: int = 60               # Skip initial fiber coupling region
    center_freq_mhz: int = 200               # MHz - RF demodulation frequency


@dataclass
class UploadParams:
    """
    Data upload configuration parameters.

    Controls how processed data is transferred from FPGA to host PC.
    Channel configuration affects memory allocation and processing requirements.

    Attributes:
        channel_num: Number of active channels (1, 2, or 4)
        data_source: Processing stage to upload (see DataSource enum)
        data_rate: Sampling interval in ns (affects bandwidth and fiber length)

    Note: 4-channel mode only supports PHASE data source due to bandwidth limits
    """
    channel_num: int = 1                     # 1, 2, or 4 channels
    data_source: int = DataSource.PHASE      # Recommended for best performance
    data_rate: int = 1                       # ns per sample (1=1GHz, 2=500MHz, etc)


@dataclass
class PhaseDemodParams:
    """
    Advanced phase demodulation algorithm parameters.

    These parameters control the FPGA-based phase processing pipeline.
    Optimization may be needed for specific fiber types or applications.

    Attributes:
        rate2phase: Decimation factor (1,2,3,4,5,10) - affects final data rate
        space_avg_order: Spatial averaging kernel size (reduces noise)
        merge_point_num: Spatial point merging factor (reduces data volume)
        diff_order: Differential order (0=absolute, 1=first derivative, etc)
        detrend_bw: High-pass filter bandwidth in Hz (removes DC drift)
        polarization_diversity: Enable polarization diversity processing

    Note: Higher space_avg_order improves SNR but reduces spatial resolution
    """
    rate2phase: int = 1                      # 250MHz base / rate2phase = final rate
    space_avg_order: int = 25                # Spatial averaging points
    merge_point_num: int = 25                # Spatial merging factor
    diff_order: int = 1                      # Differential processing order
    detrend_bw: float = 10                  # Hz - high-pass cutoff frequency
    polarization_diversity: bool = True     # Advanced polarization processing


@dataclass
class TimeSpaceParams:
    """
    Time-Space plot configuration parameters.

    Controls the 2D time-space plot visualization including rolling window
    behavior, spatial range selection, downsampling, and colormap settings.

    Attributes:
        window_frames: Number of frames to keep in rolling window (temporal dimension)
        distance_range_start: Starting distance index for display
        distance_range_end: Ending distance index for display
        time_downsample: Time dimension downsampling factor (1=no downsampling)
        space_downsample: Space dimension downsampling factor (1=no downsampling)
        colormap_type: Colormap type for 2D visualization
        vmin: Minimum value for color mapping
        vmax: Maximum value for color mapping

    Performance: Larger windows and lower downsampling provide better visualization
                but require more memory and processing power.
    """
    window_frames: int = 5                   # Rolling window size in frames
    distance_range_start: int = 40          # Start index for distance range (updated default)
    distance_range_end: int = 100           # End index for distance range (updated default)
    time_downsample: int = 50               # Time downsampling factor
    space_downsample: int = 2               # Space downsampling factor
    colormap_type: str = "jet"              # PyQtGraph colormap name
    vmin: float = -0.02                     # Color range minimum (updated for phase data)
    vmax: float = 0.02                      # Color range maximum (updated for phase data)


@dataclass
class DisplayParams:
    """
    Real-time display configuration parameters.

    Controls GUI visualization without affecting data acquisition.
    These parameters can be changed during operation without disruption.

    Attributes:
        mode: Display mode (TIME/SPACE - see DisplayMode enum)
        region_index: Spatial position for SPACE mode display
        frame_num: Number of frames to process/display
        spectrum_enable: Enable FFT spectrum analysis display
        psd_enable: Show Power Spectral Density instead of Power Spectrum
        rad_enable: Convert phase data to radians for display (storage unaffected)

    Performance: Large frame_num values may impact GUI responsiveness
    """
    mode: int = DisplayMode.TIME
    region_index: int = 0                    # Spatial position index for SPACE mode
    frame_num: int = 1024                    # Frames to display/analyze
    spectrum_enable: bool = True             # Enable frequency domain analysis
    psd_enable: bool = False                 # Power Spectral Density vs Power Spectrum
    rad_enable: bool = True                  # Display-only radian conversion (default enabled)


@dataclass
class SaveParams:
    """
    Data storage configuration parameters.

    Controls automatic data logging to disk. File splitting prevents
    excessively large files and improves data management.

    Attributes:
        enable: Enable/disable automatic data saving
        path: Directory path for data files (must exist and be writable)
        file_prefix: Optional prefix for generated filenames
        frames_per_file: Automatic file splitting threshold

    Filename Format: {seq}-eDAS-{rate}Hz-{points}pt-{timestamp}.{ms}.bin
    Storage Format: Raw int32 phase data (4 bytes per point)

    Note: Ensure sufficient disk space - typical rate ~50-200 MB/min
    """
    enable: bool = False
    path: str = "D:/eDAS_DATA"               # Default storage directory
    file_prefix: str = ""                    # Optional filename prefix
    frames_per_file: int = 10                # Auto-split after N frames


@dataclass
class AllParams:
    """
    Master parameter container.

    Aggregates all configuration parameters into a single structure
    for easy passing between modules and serialization.

    Usage:
        params = AllParams()
        params.basic.scan_rate = 5000
        params.save.enable = True

    Validation: Always validate parameters before hardware configuration
    """
    basic: BasicParams = field(default_factory=BasicParams)
    upload: UploadParams = field(default_factory=UploadParams)
    phase_demod: PhaseDemodParams = field(default_factory=PhaseDemodParams)
    display: DisplayParams = field(default_factory=DisplayParams)
    save: SaveParams = field(default_factory=SaveParams)
    time_space: TimeSpaceParams = field(default_factory=TimeSpaceParams)


# ----- GUI OPTION MAPPINGS -----
# Human-readable labels mapped to internal values for combo box controls

CHANNEL_NUM_OPTIONS: List[Tuple[str, int]] = [
    ("1", 1),    # Single channel mode
    ("2", 2),    # Dual channel mode
    ("4", 4),    # Quad channel mode (PHASE data only)
]

DATA_SOURCE_OPTIONS: List[Tuple[str, int]] = [
    ("RawBack", DataSource.raw),             # Raw ADC data
    ("I/Q", DataSource.I_Q),                 # I/Q demodulated signals
    ("Arctan", DataSource.arc),              # Arctan phase calculation
    ("Phase", DataSource.PHASE),             # Phase demodulated (recommended)
]

DATA_RATE_OPTIONS: List[Tuple[str, int]] = [
    ("1ns (1GHz)", 1),       # Highest resolution, maximum data rate
    ("2ns (500MHz)", 2),     # 2x decimation
    ("4ns (250MHz)", 4),     # 4x decimation
    ("8ns (125MHz)", 8),     # 8x decimation, lowest data rate
]

# Rate2Phase decimation options with calculated output rates
# Base rate after I/Q demodulation: 250MHz
# Final rate = 250MHz / rate2phase_factor
RATE2PHASE_OPTIONS: List[Tuple[str, int]] = [
    ("250M", 1),     # 250MHz / 1 = 250MHz (maximum rate)
    ("125M", 2),     # 250MHz / 2 = 125MHz
    ("83.33M", 3),   # 250MHz / 3 = 83.33MHz
    ("62.5M", 4),    # 250MHz / 4 = 62.5MHz
    ("50M", 5),      # 250MHz / 5 = 50MHz
    ("25M", 10),     # 250MHz / 10 = 25MHz (minimum rate)
]


# ----- HARDWARE CONSTRAINTS -----
# Maximum sampling points per channel (memory and bandwidth limitations)

MAX_POINT_NUM_1CH = 262144    # Single channel: 256K points max
MAX_POINT_NUM_2CH = 131072    # Dual channel: 128K points max (shared bandwidth)
MAX_POINT_NUM_4CH = 65536     # Quad channel: 64K points max (shared bandwidth)

# Memory alignment requirements for efficient DMA transfer
POINT_NUM_ALIGN_1CH = 512     # Single channel: 512-point alignment
POINT_NUM_ALIGN_2CH = 256     # Dual channel: 256-point alignment
POINT_NUM_ALIGN_4CH = 128     # Quad channel: 128-point alignment

# DMA memory alignment requirement (PCIe hardware constraint)
DMA_ALIGNMENT = 4096          # 4KB page alignment for optimal performance


# ----- ERROR CODE DEFINITIONS -----
# Standard error codes returned by PCIe-7821 API functions

ERROR_CODES: Dict[int, str] = {
    0: "Success",                    # Operation completed successfully
    -1: "Device open failed",        # Cannot access PCIe hardware
    -2: "Invalid parameter",         # Parameter validation failed
    -3: "Buffer overflow",           # Data buffer full, frames dropped
    -4: "Device not started",        # Acquisition not initiated
    -5: "DMA error",                 # Hardware DMA transfer error
}


def get_error_message(code: int) -> str:
    """
    Retrieve human-readable error message for API error codes.

    Args:
        code: Integer error code returned by PCIe-7821 API

    Returns:
        String description of the error condition

    Usage:
        result = api.start_acquisition()
        if result != 0:
            print(f"Error: {get_error_message(result)}")
    """
    return ERROR_CODES.get(code, f"Unknown error ({code})")


# ----- VALIDATION FUNCTIONS -----

def validate_point_num(point_num: int, channel_num: int) -> Tuple[bool, str]:
    """
    Validate point_num_per_scan against channel-specific constraints.

    PCIe-7821 has different memory and bandwidth limitations depending on
    the number of active channels. This function ensures parameters are
    within hardware limits and properly aligned for DMA efficiency.

    Args:
        point_num: Number of sampling points per scan
        channel_num: Number of active channels (1, 2, or 4)

    Returns:
        Tuple of (is_valid, error_message)
        is_valid: True if parameters are acceptable
        error_message: Description of constraint violation (empty if valid)

    Hardware Constraints:
        - Memory limitations reduce max points with more channels
        - DMA alignment requirements vary by channel count
        - Bandwidth sharing affects maximum achievable rates

    Usage:
        valid, msg = validate_point_num(20480, 2)
        if not valid:
            raise ValueError(f"Invalid configuration: {msg}")
    """
    # Single channel validation - highest capacity, 512-point alignment
    if channel_num == 1:
        if point_num > MAX_POINT_NUM_1CH:
            return False, f"Single channel mode: point_num must be <= {MAX_POINT_NUM_1CH}"
        if point_num % POINT_NUM_ALIGN_1CH != 0:
            return False, f"Single channel mode: point_num must be multiple of {POINT_NUM_ALIGN_1CH}"

    # Dual channel validation - shared bandwidth, 256-point alignment
    elif channel_num == 2:
        if point_num > MAX_POINT_NUM_2CH:
            return False, f"Dual channel mode: point_num must be <= {MAX_POINT_NUM_2CH}"
        if point_num % POINT_NUM_ALIGN_2CH != 0:
            return False, f"Dual channel mode: point_num must be multiple of {POINT_NUM_ALIGN_2CH}"

    # Quad channel validation - maximum sharing, 128-point alignment
    elif channel_num == 4:
        if point_num > MAX_POINT_NUM_4CH:
            return False, f"Quad channel mode: point_num must be <= {MAX_POINT_NUM_4CH}"
        if point_num % POINT_NUM_ALIGN_4CH != 0:
            return False, f"Quad channel mode: point_num must be multiple of {POINT_NUM_ALIGN_4CH}"

    return True, ""


def calculate_fiber_length(point_num: int, data_rate: int, data_source: int, rate2phase: int) -> float:
    """
    Calculate equivalent fiber length based on acquisition parameters.

    Converts sampling parameters to physical fiber length using calibrated
    scaling factors. Different data sources have different spatial resolution
    characteristics due to processing differences.

    Args:
        point_num: Number of sampling points per scan
        data_rate: Sampling interval in nanoseconds
        data_source: Data processing stage (see DataSource enum)
        rate2phase: Phase decimation factor (for PHASE data source)

    Returns:
        Calculated fiber length in meters

    Scaling Factors:
        - Phase data: 0.4m * rate2phase per point (optimized processing)
        - Raw/I/Q data: 0.1m * data_rate per point (direct sampling)

    Physical Meaning:
        - Higher data_rate = longer sampling interval = coarser spatial resolution
        - rate2phase decimation trades spatial resolution for reduced data rate
        - Total length = points × spatial_resolution_per_point

    Usage:
        length = calculate_fiber_length(20480, 1, DataSource.PHASE, 4)
        print(f"Monitoring {length:.1f}m of fiber")
    """
    if data_source == DataSource.PHASE:
        # Phase data: optimized spatial resolution with decimation factor
        len_rbw = 0.4 * rate2phase  # meters per point
    else:
        # Raw/I/Q data: direct sampling resolution
        len_rbw = 0.1 * data_rate   # meters per point

    return point_num * len_rbw / 1000.0  # Convert to meters


def calculate_data_rate_mbps(scan_rate: int, point_num: int, channel_num: int) -> float:
    """
    Calculate sustained data rate in MB/s for bandwidth planning.

    Computes the continuous data throughput from PCIe-7821 to host based on
    acquisition parameters. Used for storage capacity planning and performance
    monitoring.

    Args:
        scan_rate: Laser scan repetition rate in Hz
        point_num: Sampling points per scan per channel
        channel_num: Number of active channels

    Returns:
        Data rate in megabytes per second (MB/s)

    Calculation:
        - Each data point is 16-bit (2 bytes) for raw data, 32-bit (4 bytes) for phase
        - Total rate = scans/sec × points/scan × bytes/point × channels
        - Result converted from bytes/s to MB/s

    Usage:
        rate = calculate_data_rate_mbps(2000, 20480, 2)
        if rate > 100:
            print(f"Warning: High data rate {rate:.1f} MB/s")

    Note: Actual rate may vary with data_source selection and compression
    """
    # Assuming 2 bytes per point (int16) - adjust for different data types if needed
    return scan_rate * point_num * 2 * channel_num / 1024.0 / 1024.0


# ----- PERFORMANCE OPTIMIZATION CONSTANTS -----
# Buffer sizes and timing parameters tuned for optimal system performance

OPTIMIZED_BUFFER_SIZES = {
    # Hardware buffer: FPGA FIFO + DMA ring buffer
    'hardware_buffer_frames': 50,           # Absorb burst traffic and timing jitter

    # Qt signal queue: Inter-thread communication buffer
    'signal_queue_frames': 20,              # Balance latency vs memory usage

    # Storage queue: Async file writing buffer (critical for continuous operation)
    'storage_queue_frames': 200,            # Large buffer prevents data loss during disk I/O stalls

    # Display buffer: GUI visualization history
    'display_buffer_frames': 30             # Sufficient for smooth plotting updates
}

# Dynamic polling configuration for adaptive CPU usage
POLLING_CONFIG = {
    # High-frequency polling: Maximum responsiveness during heavy data flow
    'high_freq_interval_ms': 1,             # 1ms polling = ~1000 checks/sec

    # Low-frequency polling: CPU conservation during idle periods
    'low_freq_interval_ms': 10,             # 10ms polling = ~100 checks/sec

    # Adaptive switching thresholds based on buffer occupancy
    'buffer_threshold_high': 0.8,           # Switch to high freq when buffer > 80% full
    'buffer_threshold_low': 0.3             # Switch to low freq when buffer < 30% full
}

# System monitoring update intervals for GUI status displays
MONITOR_UPDATE_INTERVALS = {
    # Buffer status: Real-time monitoring for performance feedback
    'buffer_status_ms': 500,                # 2 Hz update rate balances accuracy vs overhead

    # System resources: Slower updates for CPU/disk/memory status
    'system_status_s': 10,                  # 0.1 Hz update sufficient for resource monitoring

    # Performance logging: Periodic detailed statistics capture
    'performance_log_s': 30                 # 30-second intervals for trend analysis
}