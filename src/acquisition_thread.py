"""
WFBG-7825 Data Acquisition Thread Module

QThread-based acquisition with signal-slot communication.
Key differences from PCIe-7821:
- Uses fbg_num_per_ch for phase data sizing (not point_num / merge)
- read_monitor_data requires fbg_num parameter
- Data source check: <= 1 for raw/amplitude, == 2 for phase
"""

import time
import numpy as np
from typing import Optional
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition

from wfbg7825_api import WFBG7825API, WFBG7825Error
from config import DataSource, AllParams, POLLING_CONFIG, OPTIMIZED_BUFFER_SIZES
from logger import get_logger

log = get_logger("acq_thread")

MIN_GUI_UPDATE_INTERVAL_MS = 50  # 20 FPS max


class AcquisitionThread(QThread):
    """Data acquisition thread for WFBG-7825."""

    # Signals
    data_ready = pyqtSignal(np.ndarray, int, int)        # data, data_type, channel_num
    phase_data_ready = pyqtSignal(np.ndarray, int)        # phase_data, channel_num
    monitor_data_ready = pyqtSignal(np.ndarray, int)      # monitor_data, channel_num
    buffer_status = pyqtSignal(int, int)                  # points_in_buffer, buffer_size_mb
    error_occurred = pyqtSignal(str)
    acquisition_started = pyqtSignal()
    acquisition_stopped = pyqtSignal()

    def __init__(self, api: WFBG7825API, parent=None):
        super().__init__(parent)
        self.api = api
        self._running = False
        self._paused = False

        self._params: Optional[AllParams] = None
        self._total_point_num = 0
        self._fbg_num_per_ch = 0      # From peak detection
        self._frame_num = 20
        self._channel_num = 1
        self._data_source = DataSource.PHASE

        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()

        self._frames_acquired = 0
        self._bytes_acquired = 0
        self._loop_count = 0
        self._last_log_time = 0

        self._last_gui_update_time = 0
        self._pending_phase_data = None
        self._pending_raw_data = None
        self._pending_monitor_data = None

        self._current_polling_interval = POLLING_CONFIG['low_freq_interval_ms'] / 1000.0
        self._high_freq_interval = POLLING_CONFIG['high_freq_interval_ms'] / 1000.0
        self._low_freq_interval = POLLING_CONFIG['low_freq_interval_ms'] / 1000.0
        self._buffer_threshold_high = POLLING_CONFIG['buffer_threshold_high']
        self._buffer_threshold_low = POLLING_CONFIG['buffer_threshold_low']

        log.info("AcquisitionThread initialized")

    def configure(self, params: AllParams, fbg_num_per_ch: int = 0):
        """
        Configure acquisition parameters.

        Args:
            params: Configuration parameters
            fbg_num_per_ch: FBG count per channel from peak detection
        """
        self._params = params
        self._total_point_num = params.basic.point_num_per_scan
        self._fbg_num_per_ch = fbg_num_per_ch
        self._frame_num = params.display.frame_num
        self._channel_num = params.upload.channel_num
        self._data_source = params.upload.data_source

        log.info(f"Configured: total_points={self._total_point_num}, "
                 f"fbg_num_per_ch={self._fbg_num_per_ch}, "
                 f"frames={self._frame_num}, channels={self._channel_num}, "
                 f"data_source={self._data_source}")

    def run(self):
        """Thread main loop."""
        log.info("=== Acquisition thread started ===")
        self._running = True
        self._frames_acquired = 0
        self._bytes_acquired = 0
        self._loop_count = 0
        self._last_log_time = time.time()

        self.acquisition_started.emit()

        try:
            while self._running:
                self._loop_count += 1
                loop_start = time.perf_counter()

                # Periodic status log
                now = time.time()
                if now - self._last_log_time > 5.0:
                    log.info(f"Status: loops={self._loop_count}, frames={self._frames_acquired}, "
                             f"bytes={self._bytes_acquired/1024/1024:.1f}MB")
                    self._last_log_time = now

                # Check for pause
                self._mutex.lock()
                while self._paused and self._running:
                    self._pause_condition.wait(self._mutex)
                self._mutex.unlock()

                if not self._running:
                    break

                # Determine expected data size based on data source
                if self._data_source == DataSource.PHASE:
                    expected_points = self._fbg_num_per_ch * self._frame_num
                else:
                    expected_points = self._total_point_num * self._frame_num

                # Wait for enough data in buffer
                wait_count = 0
                while self._running:
                    try:
                        points_in_buffer = self.api.query_buffer_points()

                        if wait_count % 100 == 0:
                            buffer_mb = points_in_buffer * self._channel_num * 2 // (1024 * 1024)
                            self.buffer_status.emit(points_in_buffer, buffer_mb)

                        if points_in_buffer >= expected_points:
                            break

                        self._adjust_polling_interval(points_in_buffer, expected_points)
                        time.sleep(self._current_polling_interval)
                        wait_count += 1

                        if wait_count > 5000:
                            log.error(f"Timeout waiting for data! in_buf={points_in_buffer}, expected={expected_points}")
                            self.error_occurred.emit("Timeout waiting for data")
                            break
                    except Exception as e:
                        if not self._running:
                            break
                        log.warning(f"Error querying buffer: {e}")
                        time.sleep(self._current_polling_interval)
                        wait_count += 1

                if not self._running:
                    break

                # Read data
                try:
                    if self._data_source == DataSource.PHASE:
                        self._read_phase_data()
                    else:
                        self._read_raw_data()
                except WFBG7825Error as e:
                    log.error(f"Read error: {e}")
                    self.error_occurred.emit(str(e))
                    time.sleep(0.1)
                    continue
                except Exception as e:
                    if not self._running:
                        break
                    log.error(f"Unexpected read error: {e}")
                    self.error_occurred.emit(f"Read error: {e}")
                    time.sleep(0.1)
                    continue

                self._frames_acquired += self._frame_num

                loop_time = (time.perf_counter() - loop_start) * 1000
                if loop_time > 100:
                    log.warning(f"Slow loop iteration: {loop_time:.1f}ms")

        except Exception as e:
            log.exception(f"Unexpected acquisition error: {e}")
            self.error_occurred.emit(f"Acquisition error: {e}")

        finally:
            log.info(f"=== Acquisition thread stopped === (loops={self._loop_count}, frames={self._frames_acquired})")
            self.acquisition_stopped.emit()

    def _read_raw_data(self):
        """Read raw/amplitude data."""
        points_per_ch = self._total_point_num * self._frame_num

        data, points_returned = self.api.read_data(points_per_ch, self._channel_num)
        self._bytes_acquired += len(data) * 2

        if self._channel_num > 1:
            data = data.reshape(-1, self._channel_num)

        self._pending_raw_data = (data, self._data_source, self._channel_num)
        self._emit_if_ready()

    def _read_phase_data(self):
        """Read phase data using fbg_num semantics."""
        fbg_points_per_ch = self._fbg_num_per_ch * self._frame_num

        phase_data, points_returned = self.api.read_phase_data(fbg_points_per_ch, self._channel_num)
        self._bytes_acquired += len(phase_data) * 4

        if self._channel_num > 1:
            phase_data = phase_data.reshape(-1, self._channel_num)

        self._pending_phase_data = (phase_data, self._channel_num)

        # Also read monitor data
        try:
            monitor_data = self.api.read_monitor_data(self._fbg_num_per_ch, self._channel_num)
            self._pending_monitor_data = (monitor_data, self._channel_num)
        except WFBG7825Error as e:
            log.warning(f"Monitor data read failed (non-critical): {e}")
        except Exception as e:
            log.warning(f"Monitor data read failed (non-critical): {e}")

        self._emit_if_ready()

    def _emit_if_ready(self):
        """Emit pending data signals if enough time has passed."""
        current_time = time.perf_counter() * 1000
        elapsed = current_time - self._last_gui_update_time

        if elapsed < MIN_GUI_UPDATE_INTERVAL_MS:
            return

        signals_emitted = 0

        if self._pending_phase_data is not None:
            phase_data, channel_num = self._pending_phase_data
            self.phase_data_ready.emit(phase_data, channel_num)
            self._pending_phase_data = None
            signals_emitted += 1

        if self._pending_raw_data is not None:
            data, data_source, channel_num = self._pending_raw_data
            self.data_ready.emit(data, data_source, channel_num)
            self._pending_raw_data = None
            signals_emitted += 1

        if self._pending_monitor_data is not None:
            monitor_data, channel_num = self._pending_monitor_data
            self.monitor_data_ready.emit(monitor_data, channel_num)
            self._pending_monitor_data = None
            signals_emitted += 1

        if signals_emitted > 0:
            self._last_gui_update_time = current_time

    def _adjust_polling_interval(self, points_in_buffer: int, expected_points: int):
        if expected_points == 0:
            return

        buffer_usage_ratio = points_in_buffer / expected_points

        if buffer_usage_ratio >= self._buffer_threshold_high:
            self._current_polling_interval = self._high_freq_interval
        elif buffer_usage_ratio <= self._buffer_threshold_low:
            self._current_polling_interval = self._low_freq_interval

    def stop(self):
        log.info("Stop requested")
        self._running = False

        self._mutex.lock()
        self._paused = False
        self._pause_condition.wakeAll()
        self._mutex.unlock()

        if self.isRunning():
            if not self.wait(3000):
                log.warning("Thread did not finish in 3 seconds! Terminating...")
                self.terminate()
                self.wait(1000)

    def pause(self):
        self._mutex.lock()
        self._paused = True
        self._mutex.unlock()

    def resume(self):
        self._mutex.lock()
        self._paused = False
        self._pause_condition.wakeAll()
        self._mutex.unlock()

    @property
    def is_running(self) -> bool:
        return self._running and self.isRunning()

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def frames_acquired(self) -> int:
        return self._frames_acquired

    @property
    def bytes_acquired(self) -> int:
        return self._bytes_acquired

    @property
    def fbg_num_per_ch(self) -> int:
        return self._fbg_num_per_ch

    @property
    def total_point_num(self) -> int:
        return self._total_point_num


class SimulatedAcquisitionThread(AcquisitionThread):
    """Simulated acquisition thread for testing without hardware."""

    def __init__(self, parent=None):
        log.info("Creating SimulatedAcquisitionThread")

        class MockAPI:
            def query_buffer_points(self):
                return 100000

            def read_data(self, n, c):
                return np.random.randint(-32768, 32767, n*c, dtype=np.int16), n

            def read_phase_data(self, n, c):
                return np.random.randint(-100000, 100000, n*c, dtype=np.int32), n

            def read_monitor_data(self, n, c):
                return np.random.randint(0, 65535, n*c, dtype=np.uint32)

        self._mock_api = MockAPI()
        super().__init__(self._mock_api, parent)

    def run(self):
        """Simulated acquisition loop."""
        log.info("=== Simulated acquisition thread started ===")
        self._running = True
        self._frames_acquired = 0
        self._bytes_acquired = 0
        self._loop_count = 0
        self._last_log_time = time.time()

        self.acquisition_started.emit()

        try:
            while self._running:
                self._loop_count += 1

                now = time.time()
                if now - self._last_log_time > 5.0:
                    log.info(f"Simulation status: loops={self._loop_count}, frames={self._frames_acquired}")
                    self._last_log_time = now

                self._mutex.lock()
                while self._paused and self._running:
                    self._pause_condition.wait(self._mutex)
                self._mutex.unlock()

                if not self._running:
                    break

                # Simulate acquisition delay
                scan_rate = self._params.basic.scan_rate if self._params else 2000
                delay = self._frame_num / max(scan_rate, 1)
                time.sleep(delay)

                if self._data_source == DataSource.PHASE:
                    # Use fbg_num_per_ch for phase data sizing
                    fbg_num = max(self._fbg_num_per_ch, 100)  # Fallback to 100 for simulation
                    points = fbg_num * self._frame_num
                    phase_data = np.random.randint(-100000, 100000, points * self._channel_num, dtype=np.int32)

                    if self._channel_num > 1:
                        phase_data = phase_data.reshape(-1, self._channel_num)

                    self._pending_phase_data = (phase_data, self._channel_num)
                    self._bytes_acquired += len(phase_data.flatten()) * 4

                    # Simulated monitor data
                    monitor_data = np.random.randint(0, 65535, fbg_num * self._channel_num, dtype=np.uint32)
                    self._pending_monitor_data = (monitor_data, self._channel_num)
                else:
                    points = self._total_point_num * self._frame_num
                    data = np.random.randint(-32768, 32767, points * self._channel_num, dtype=np.int16)

                    if self._channel_num > 1:
                        data = data.reshape(-1, self._channel_num)

                    self._pending_raw_data = (data, self._data_source, self._channel_num)
                    self._bytes_acquired += len(data.flatten()) * 2

                self._emit_if_ready()

                if self._loop_count % 10 == 0:
                    self.buffer_status.emit(100000, 10)

                self._frames_acquired += self._frame_num

        except Exception as e:
            log.exception(f"Simulation error: {e}")
            self.error_occurred.emit(f"Simulation error: {e}")

        finally:
            log.info(f"=== Simulated acquisition thread stopped === (loops={self._loop_count})")
            self.acquisition_stopped.emit()
