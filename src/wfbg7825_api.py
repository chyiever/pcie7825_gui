"""
WFBG-7825 DLL Wrapper Module

Python interface to wfbg7825_api.dll via ctypes.
Handles DMA buffer alignment, thread-safe DLL calls, and error translation.

Key differences from PCIe-7821:
- set_trig_param() is a single combined call (not 3 separate functions)
- set_upload_data_param() has no data_rate parameter
- set_phase_dem_param() has only 2 params (polarization, detrend)
- get_peak_info(), set_peak_info(), get_valid_fbg_num() are NEW
- read_monitor_data() requires fbg_num parameter
- read_phase_data() uses fbg_num semantics
"""

import ctypes
import numpy as np
from pathlib import Path
from typing import Optional, Tuple
import os
import time
import threading

from config import DMA_ALIGNMENT, get_error_message
from logger import get_logger, PerformanceTimer

log = get_logger("api")


class AlignedBuffer:
    """Memory buffer with specified alignment for DMA transfers."""

    def __init__(self, size: int, dtype: np.dtype, alignment: int = DMA_ALIGNMENT):
        self.size = size
        self.dtype = np.dtype(dtype)
        self.alignment = alignment
        self.itemsize = self.dtype.itemsize

        total_bytes = size * self.itemsize + alignment
        self._raw_buffer = (ctypes.c_char * total_bytes)()

        raw_addr = ctypes.addressof(self._raw_buffer)
        offset = (alignment - (raw_addr % alignment)) % alignment

        self.array = np.frombuffer(
            self._raw_buffer,
            dtype=self.dtype,
            count=size,
            offset=offset
        )

        self._aligned_addr = raw_addr + offset

        log.debug(f"AlignedBuffer created: size={size}, dtype={dtype}, "
                  f"aligned_addr=0x{self._aligned_addr:X}, alignment_ok={self._aligned_addr % alignment == 0}")

    def get_ctypes_ptr(self):
        """Get ctypes pointer to aligned buffer."""
        if self.dtype == np.int16:
            return ctypes.cast(self._aligned_addr, ctypes.POINTER(ctypes.c_short))
        elif self.dtype == np.int32:
            return ctypes.cast(self._aligned_addr, ctypes.POINTER(ctypes.c_int))
        elif self.dtype == np.uint32:
            return ctypes.cast(self._aligned_addr, ctypes.POINTER(ctypes.c_uint))
        elif self.dtype == np.uint16:
            return ctypes.cast(self._aligned_addr, ctypes.POINTER(ctypes.c_ushort))
        else:
            raise ValueError(f"Unsupported dtype: {self.dtype}")

    def __del__(self):
        self._raw_buffer = None
        self.array = None


class WFBG7825Error(Exception):
    """Exception for WFBG-7825 API errors."""
    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.message = message or get_error_message(code)
        super().__init__(f"WFBG-7825 Error {code}: {self.message}")


class WFBG7825API:
    """Python wrapper for wfbg7825_api.dll."""

    def __init__(self, dll_path: Optional[str] = None):
        self.dll = None
        self._is_open = False
        self._lock = threading.Lock()

        log.info("Initializing WFBG7825API...")

        if dll_path is None:
            dll_path = self._find_dll()

        if not os.path.exists(dll_path):
            log.error(f"DLL not found: {dll_path}")
            raise FileNotFoundError(f"DLL not found: {dll_path}")

        log.info(f"Loading DLL from: {dll_path}")

        try:
            self.dll = ctypes.CDLL(dll_path)
            log.info("DLL loaded successfully")
        except OSError as e:
            log.error(f"Failed to load DLL: {e}")
            raise RuntimeError(f"Failed to load DLL: {e}")

        self._setup_prototypes()

        # Buffers for data reading
        self._raw_buffer: Optional[AlignedBuffer] = None
        self._phase_buffer: Optional[AlignedBuffer] = None
        self._monitor_buffer: Optional[AlignedBuffer] = None

        log.info("WFBG7825API initialized")

    def _find_dll(self) -> str:
        """Find the DLL in default locations."""
        script_dir = Path(__file__).parent
        project_root = script_dir.parent

        search_paths = [
            project_root / "libs" / "wfbg7825_api.dll",
            script_dir / "wfbg7825_api.dll",
            project_root / "wfbg7825_api.dll",
            Path("wfbg7825_api.dll"),
        ]

        for path in search_paths:
            log.debug(f"Checking DLL path: {path}")
            if path.exists():
                log.info(f"Found DLL at: {path}")
                return str(path)

        raise FileNotFoundError(
            f"wfbg7825_api.dll not found. Please copy it to: {project_root / 'libs'}"
        )

    def _setup_prototypes(self):
        """Setup ctypes function prototypes to match DLL C API signatures."""
        log.debug("Setting up function prototypes...")

        # int wfbg7825_open()
        self.dll.wfbg7825_open.restype = ctypes.c_int
        self.dll.wfbg7825_open.argtypes = []

        # void wfbg7825_close()
        self.dll.wfbg7825_close.restype = None
        self.dll.wfbg7825_close.argtypes = []

        # int wfbg7825_set_clk_src(unsigned int clk_src)
        self.dll.wfbg7825_set_clk_src.restype = ctypes.c_int
        self.dll.wfbg7825_set_clk_src.argtypes = [ctypes.c_uint]

        # int wfbg7825_set_trig_param(uint trig_dir, uint scan_rate, uint pulse_high_width_ns)
        self.dll.wfbg7825_set_trig_param.restype = ctypes.c_int
        self.dll.wfbg7825_set_trig_param.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]

        # int wfbg7825_set_origin_point_num_per_scan(uint point_num_per_scan)
        self.dll.wfbg7825_set_origin_point_num_per_scan.restype = ctypes.c_int
        self.dll.wfbg7825_set_origin_point_num_per_scan.argtypes = [ctypes.c_uint]

        # int wfbg7825_set_bypass_point_num(uint bypass_point_num)
        self.dll.wfbg7825_set_bypass_point_num.restype = ctypes.c_int
        self.dll.wfbg7825_set_bypass_point_num.argtypes = [ctypes.c_uint]

        # int wfbg7825_set_upload_data_param(uint upload_ch_num, uint upload_data_src)
        self.dll.wfbg7825_set_upload_data_param.restype = ctypes.c_int
        self.dll.wfbg7825_set_upload_data_param.argtypes = [ctypes.c_uint, ctypes.c_uint]

        # int wfbg7825_set_center_freq(uint center_freq_hz)
        self.dll.wfbg7825_set_center_freq.restype = ctypes.c_int
        self.dll.wfbg7825_set_center_freq.argtypes = [ctypes.c_uint]

        # int wfbg7825_set_phase_dem_param(uint polarization_diversity_en, double detrend_filter_bw)
        self.dll.wfbg7825_set_phase_dem_param.restype = ctypes.c_int
        self.dll.wfbg7825_set_phase_dem_param.argtypes = [ctypes.c_uint, ctypes.c_double]

        # int wfbg7825_get_peak_info(uint amp_base, double fbg_interval,
        #     uint* ch0_cnt, uint* ch0_info, ushort* ch0_amp,
        #     uint* ch1_cnt, uint* ch1_info, ushort* ch1_amp)
        self.dll.wfbg7825_get_peak_info.restype = ctypes.c_int
        self.dll.wfbg7825_get_peak_info.argtypes = [
            ctypes.c_uint, ctypes.c_double,
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_ushort),
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_ushort),
        ]

        # int wfbg7825_set_peak_info(uint* ch0_info, uint* ch1_info)
        self.dll.wfbg7825_set_peak_info.restype = ctypes.c_int
        self.dll.wfbg7825_set_peak_info.argtypes = [
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)
        ]

        # int wfbg7825_get_valid_fbg_num(uint* fbg_num)
        self.dll.wfbg7825_get_valid_fbg_num.restype = ctypes.c_int
        self.dll.wfbg7825_get_valid_fbg_num.argtypes = [ctypes.POINTER(ctypes.c_uint)]

        # int wfbg7825_point_num_per_ch_in_buf_query(uint* p_point_num_in_buf_per_ch)
        self.dll.wfbg7825_point_num_per_ch_in_buf_query.restype = ctypes.c_int
        # 使用灵活的参数类型定义，支持多种无符号整型
        try:
            from ctypes import wintypes
            self.dll.wfbg7825_point_num_per_ch_in_buf_query.argtypes = [ctypes.POINTER(wintypes.DWORD)]
        except ImportError:
            self.dll.wfbg7825_point_num_per_ch_in_buf_query.argtypes = [ctypes.POINTER(ctypes.c_uint)]

        # int wfbg7825_read_data(uint point_num_per_ch, short* p_data, uint* p_returned)
        self.dll.wfbg7825_read_data.restype = ctypes.c_int
        self.dll.wfbg7825_read_data.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_short),
            ctypes.POINTER(ctypes.c_uint)
        ]

        # int wfbg7825_read_phase_data(uint fbg_num_per_ch, int* p_phase, uint* p_returned)
        self.dll.wfbg7825_read_phase_data.restype = ctypes.c_int
        self.dll.wfbg7825_read_phase_data.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint)
        ]

        # int wfbg7825_read_monitor_data(uint fbg_num_per_ch, uint* p_monitor_data)
        self.dll.wfbg7825_read_monitor_data.restype = ctypes.c_int
        self.dll.wfbg7825_read_monitor_data.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint)
        ]

        # int wfbg7825_start(void)
        self.dll.wfbg7825_start.restype = ctypes.c_int
        self.dll.wfbg7825_start.argtypes = []

        # int wfbg7825_stop(void)
        self.dll.wfbg7825_stop.restype = ctypes.c_int
        self.dll.wfbg7825_stop.argtypes = []

        # int wfbg7825_test_wr_reg(uint addr, uint data)
        self.dll.wfbg7825_test_wr_reg.restype = ctypes.c_int
        self.dll.wfbg7825_test_wr_reg.argtypes = [ctypes.c_uint, ctypes.c_uint]

        # int wfbg7825_test_rd_reg(uint addr, uint* data)
        self.dll.wfbg7825_test_rd_reg.restype = ctypes.c_int
        self.dll.wfbg7825_test_rd_reg.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]

        log.debug("Function prototypes setup complete")

    def _check_result(self, result: int, operation: str = ""):
        """Check API result and raise exception on error."""
        if result != 0:
            log.error(f"{operation} failed with code {result}: {get_error_message(result)}")
            raise WFBG7825Error(result, f"{operation}: {get_error_message(result)}")

    # ----- DEVICE CONTROL -----

    def open(self) -> int:
        log.info("Opening device...")
        with self._lock:
            start = time.perf_counter()
            result = self.dll.wfbg7825_open()
            elapsed = (time.perf_counter() - start) * 1000

            if result == 0:
                self._is_open = True
                log.info(f"Device opened successfully in {elapsed:.1f} ms")
            else:
                log.error(f"Failed to open device: error code {result}")

            return result

    def close(self):
        log.info("Closing device...")
        with self._lock:
            if self.dll is not None:
                self.dll.wfbg7825_close()
                self._is_open = False
                log.info("Device closed")

            self._raw_buffer = None
            self._phase_buffer = None
            self._monitor_buffer = None

    @property
    def is_open(self) -> bool:
        return self._is_open

    # ----- HARDWARE CONFIGURATION -----

    def set_clk_src(self, clk_src: int) -> int:
        log.debug(f"set_clk_src({clk_src})")
        with self._lock:
            result = self.dll.wfbg7825_set_clk_src(clk_src)
        log.debug(f"set_clk_src result: {result}")
        return result

    def set_trig_param(self, trig_dir: int, scan_rate: int, pulse_width_ns: int) -> int:
        """Set trigger parameters (combined call for 7825)."""
        log.debug(f"set_trig_param(trig_dir={trig_dir}, scan_rate={scan_rate}, pulse_ns={pulse_width_ns})")
        with self._lock:
            result = self.dll.wfbg7825_set_trig_param(trig_dir, scan_rate, pulse_width_ns)
        log.debug(f"set_trig_param result: {result}")
        return result

    def set_origin_point_num_per_scan(self, point_num: int) -> int:
        log.debug(f"set_origin_point_num_per_scan({point_num})")
        with self._lock:
            result = self.dll.wfbg7825_set_origin_point_num_per_scan(point_num)
        log.debug(f"set_origin_point_num_per_scan result: {result}")
        return result

    def set_bypass_point_num(self, bypass_num: int) -> int:
        log.debug(f"set_bypass_point_num({bypass_num})")
        with self._lock:
            result = self.dll.wfbg7825_set_bypass_point_num(bypass_num)
        log.debug(f"set_bypass_point_num result: {result}")
        return result

    def set_upload_data_param(self, ch_num: int, data_src: int) -> int:
        """Set upload data parameters (no data_rate for 7825)."""
        log.debug(f"set_upload_data_param(ch_num={ch_num}, data_src={data_src})")
        with self._lock:
            result = self.dll.wfbg7825_set_upload_data_param(ch_num, data_src)
        log.debug(f"set_upload_data_param result: {result}")
        return result

    def set_center_freq(self, freq_hz: int) -> int:
        log.debug(f"set_center_freq({freq_hz})")
        with self._lock:
            result = self.dll.wfbg7825_set_center_freq(freq_hz)
        log.debug(f"set_center_freq result: {result}")
        return result

    def set_phase_dem_param(self, polarization_en: bool, detrend_bw: float) -> int:
        """Set phase demodulation parameters (only 2 params for 7825)."""
        log.debug(f"set_phase_dem_param(polar_en={polarization_en}, detrend_bw={detrend_bw})")
        with self._lock:
            result = self.dll.wfbg7825_set_phase_dem_param(int(polarization_en), detrend_bw)
        log.debug(f"set_phase_dem_param result: {result}")
        return result

    # ----- PEAK DETECTION (NEW for 7825) -----

    def get_peak_info(self, amp_base_line: int, fbg_interval_m: float,
                      point_num_per_scan: int) -> Tuple[int, np.ndarray, np.ndarray, int, np.ndarray, np.ndarray]:
        """
        Get FBG peak information.

        Args:
            amp_base_line: Amplitude threshold for peak detection
            fbg_interval_m: FBG spacing in meters
            point_num_per_scan: Points per scan (for array allocation)

        Returns:
            (ch0_peak_cnt, ch0_peak_info, ch0_amp, ch1_peak_cnt, ch1_peak_info, ch1_amp)
        """
        log.info(f"get_peak_info(amp_base={amp_base_line}, interval={fbg_interval_m}m, points={point_num_per_scan})")

        # Allocate arrays
        ch0_peak_cnt = ctypes.c_uint()
        ch1_peak_cnt = ctypes.c_uint()

        ch0_peak_info = (ctypes.c_uint * point_num_per_scan)()
        ch1_peak_info = (ctypes.c_uint * point_num_per_scan)()
        ch0_amp = (ctypes.c_ushort * point_num_per_scan)()
        ch1_amp = (ctypes.c_ushort * point_num_per_scan)()

        with self._lock:
            start = time.perf_counter()
            result = self.dll.wfbg7825_get_peak_info(
                amp_base_line, fbg_interval_m,
                ctypes.byref(ch0_peak_cnt), ch0_peak_info, ch0_amp,
                ctypes.byref(ch1_peak_cnt), ch1_peak_info, ch1_amp
            )
            elapsed = (time.perf_counter() - start) * 1000

        if result != 0:
            log.error(f"get_peak_info failed: code {result}")
            raise WFBG7825Error(result, "get_peak_info")

        # Convert to numpy arrays
        ch0_info_arr = np.ctypeslib.as_array(ch0_peak_info).copy()
        ch1_info_arr = np.ctypeslib.as_array(ch1_peak_info).copy()
        ch0_amp_arr = np.ctypeslib.as_array(ch0_amp).copy()
        ch1_amp_arr = np.ctypeslib.as_array(ch1_amp).copy()

        log.info(f"get_peak_info: ch0_peaks={ch0_peak_cnt.value}, ch1_peaks={ch1_peak_cnt.value}, "
                 f"time={elapsed:.1f}ms")

        return (ch0_peak_cnt.value, ch0_info_arr, ch0_amp_arr,
                ch1_peak_cnt.value, ch1_info_arr, ch1_amp_arr)

    def set_peak_info(self, ch0_peak_info: np.ndarray, ch1_peak_info: np.ndarray) -> int:
        """Set custom peak info (optional, get_peak_info already sets it)."""
        log.debug("set_peak_info")
        ch0_arr = ch0_peak_info.astype(np.uint32)
        ch1_arr = ch1_peak_info.astype(np.uint32)

        ch0_ptr = ch0_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint))
        ch1_ptr = ch1_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint))

        with self._lock:
            result = self.dll.wfbg7825_set_peak_info(ch0_ptr, ch1_ptr)
        log.debug(f"set_peak_info result: {result}")
        return result

    def get_valid_fbg_num(self) -> int:
        """Get the number of valid FBGs on the fiber."""
        fbg_num = ctypes.c_uint()
        with self._lock:
            result = self.dll.wfbg7825_get_valid_fbg_num(ctypes.byref(fbg_num))

        if result != 0:
            log.error(f"get_valid_fbg_num failed: code {result}")
            raise WFBG7825Error(result, "get_valid_fbg_num")

        log.info(f"Valid FBG num: {fbg_num.value}")
        return fbg_num.value

    # ----- DATA READING -----

    def query_buffer_points(self) -> int:
        """Query number of points per channel in buffer."""
        try:
            # 使用wintypes中的DWORD类型，在Windows上更稳定
            from ctypes import wintypes
            point_num = wintypes.DWORD()
            log.debug(f"Created point_num: {point_num}, type: {type(point_num)}")

            with self._lock:
                start = time.perf_counter()
                result = self.dll.wfbg7825_point_num_per_ch_in_buf_query(ctypes.byref(point_num))
                elapsed = (time.perf_counter() - start) * 1000

            if elapsed > 10:
                log.warning(f"query_buffer_points took {elapsed:.1f} ms, points={point_num.value}")

            # 检查API调用结果
            if result != 0:
                log.warning(f"query_buffer_points returned error code: {result}")
                return 0

            return point_num.value

        except ImportError:
            # 如果wintypes不可用，回退到原始方法
            log.debug("wintypes not available, using c_uint")
            point_num = ctypes.c_uint()

            with self._lock:
                start = time.perf_counter()
                result = self.dll.wfbg7825_point_num_per_ch_in_buf_query(ctypes.byref(point_num))
                elapsed = (time.perf_counter() - start) * 1000

            if elapsed > 10:
                log.warning(f"query_buffer_points took {elapsed:.1f} ms, points={point_num.value}")

            if result != 0:
                log.warning(f"query_buffer_points returned error code: {result}")
                return 0

            return point_num.value

        except Exception as e:
            log.error(f"query_buffer_points error details: {e}, type: {type(e)}")
            return 0

    def allocate_buffers(self, point_num: int, channel_num: int, frame_num: int,
                         fbg_num_per_ch: int = 0):
        """
        Allocate aligned buffers for data reading.

        Args:
            point_num: Points per scan (for raw/amplitude data)
            channel_num: Number of channels
            frame_num: Number of frames
            fbg_num_per_ch: FBG count per channel (for phase data)
        """
        log.info(f"Allocating buffers: point_num={point_num}, channels={channel_num}, "
                 f"frames={frame_num}, fbg_num={fbg_num_per_ch}")

        # Raw data buffer (short) - for raw/amplitude
        raw_size = point_num * channel_num * frame_num
        self._raw_buffer = AlignedBuffer(raw_size, np.int16)
        log.debug(f"Raw buffer allocated: {raw_size * 2 / 1024 / 1024:.2f} MB")

        # Phase data buffer (int32) - uses fbg_num_per_ch
        if fbg_num_per_ch > 0:
            phase_size = fbg_num_per_ch * channel_num * frame_num
            self._phase_buffer = AlignedBuffer(phase_size, np.int32)
            log.debug(f"Phase buffer allocated: {phase_size * 4 / 1024 / 1024:.2f} MB")

            # Monitor data buffer (uint32)
            monitor_size = fbg_num_per_ch * channel_num
            self._monitor_buffer = AlignedBuffer(monitor_size, np.uint32)
            log.debug(f"Monitor buffer allocated: {monitor_size * 4 / 1024:.2f} KB")

        log.info("Buffer allocation complete")

    def read_data(self, point_num_per_ch: int, channel_num: int) -> Tuple[np.ndarray, int]:
        """Read raw/amplitude data from device."""
        total_points = point_num_per_ch * channel_num

        if self._raw_buffer is None or self._raw_buffer.size < total_points:
            log.debug(f"Reallocating raw buffer: {total_points} points")
            self._raw_buffer = AlignedBuffer(total_points, np.int16)

        points_returned = ctypes.c_uint()

        with self._lock:
            start = time.perf_counter()
            result = self.dll.wfbg7825_read_data(
                point_num_per_ch,
                self._raw_buffer.get_ctypes_ptr(),
                ctypes.byref(points_returned)
            )
            elapsed = (time.perf_counter() - start) * 1000

        if result != 0:
            log.error(f"read_data failed: code {result}")
            raise WFBG7825Error(result, "read_data")

        log.debug(f"read_data: requested={point_num_per_ch}, returned={points_returned.value}, "
                  f"time={elapsed:.1f}ms")

        return self._raw_buffer.array[:total_points].copy(), points_returned.value

    def read_phase_data(self, fbg_num_per_ch: int, channel_num: int) -> Tuple[np.ndarray, int]:
        """Read phase data from device using fbg_num semantics."""
        total_points = fbg_num_per_ch * channel_num

        if self._phase_buffer is None or self._phase_buffer.size < total_points:
            log.debug(f"Reallocating phase buffer: {total_points} points")
            self._phase_buffer = AlignedBuffer(total_points, np.int32)

        points_returned = ctypes.c_uint()

        with self._lock:
            start = time.perf_counter()
            result = self.dll.wfbg7825_read_phase_data(
                fbg_num_per_ch,
                self._phase_buffer.get_ctypes_ptr(),
                ctypes.byref(points_returned)
            )
            elapsed = (time.perf_counter() - start) * 1000

        if result != 0:
            log.error(f"read_phase_data failed: code {result}")
            raise WFBG7825Error(result, "read_phase_data")

        log.debug(f"read_phase_data: requested={fbg_num_per_ch}, returned={points_returned.value}, "
                  f"time={elapsed:.1f}ms")

        return self._phase_buffer.array[:total_points].copy(), points_returned.value

    def read_monitor_data(self, fbg_num_per_ch: int, channel_num: int) -> np.ndarray:
        """Read monitor data (requires fbg_num param for 7825)."""
        total_points = fbg_num_per_ch * channel_num

        if self._monitor_buffer is None or self._monitor_buffer.size < total_points:
            log.debug(f"Reallocating monitor buffer: {total_points} points")
            self._monitor_buffer = AlignedBuffer(total_points, np.uint32)

        with self._lock:
            start = time.perf_counter()
            result = self.dll.wfbg7825_read_monitor_data(
                fbg_num_per_ch,
                self._monitor_buffer.get_ctypes_ptr()
            )
            elapsed = (time.perf_counter() - start) * 1000

        if result != 0:
            log.error(f"read_monitor_data failed: code {result}")
            raise WFBG7825Error(result, "read_monitor_data")

        log.debug(f"read_monitor_data: fbg_num={fbg_num_per_ch}, time={elapsed:.1f}ms")

        return self._monitor_buffer.array[:total_points].copy()

    def start(self) -> int:
        log.info("Starting acquisition...")
        with self._lock:
            start = time.perf_counter()
            result = self.dll.wfbg7825_start()
            elapsed = (time.perf_counter() - start) * 1000

        if result == 0:
            log.info(f"Acquisition started in {elapsed:.1f} ms")
        else:
            log.error(f"Failed to start acquisition: code {result}")

        return result

    def stop(self) -> int:
        log.info("Stopping acquisition...")
        with self._lock:
            start = time.perf_counter()
            result = self.dll.wfbg7825_stop()
            elapsed = (time.perf_counter() - start) * 1000

        if result == 0:
            log.info(f"Acquisition stopped in {elapsed:.1f} ms")
        else:
            log.error(f"Failed to stop acquisition: code {result}")

        return result

    # ----- REGISTER ACCESS (TEST / DEBUG) -----

    def write_reg(self, addr: int, data: int) -> int:
        if addr % 4 != 0:
            raise ValueError("Register address must be 4-byte aligned")
        log.debug(f"write_reg(addr=0x{addr:X}, data=0x{data:X})")
        with self._lock:
            result = self.dll.wfbg7825_test_wr_reg(addr, data)
        return result

    def read_reg(self, addr: int) -> int:
        if addr % 4 != 0:
            raise ValueError("Register address must be 4-byte aligned")
        data = ctypes.c_uint()
        with self._lock:
            self.dll.wfbg7825_test_rd_reg(addr, ctypes.byref(data))
        log.debug(f"read_reg(addr=0x{addr:X}) = 0x{data.value:X}")
        return data.value

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        if self._is_open:
            self.close()
