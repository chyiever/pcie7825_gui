"""
PCIe-7821 Data Acquisition Thread Module

QThread-based acquisition with signal-slot communication.
Runs hardware DMA reading in background to keep GUI responsive.

Key Design:
- Dynamic polling: adjusts interval based on buffer fill ratio
- GUI throttling: caps signal emission at ~20 FPS to prevent queue backup
- Pause/resume: QMutex + QWaitCondition for thread-safe state transitions

Classes:
- AcquisitionThread: Real hardware acquisition via DLL API
- SimulatedAcquisitionThread: Random data generator for UI testing
"""

import time
import numpy as np
from typing import Optional
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition, Qt

from pcie7821_api import PCIe7821API, PCIe7821Error
from config import DataSource, AllParams, POLLING_CONFIG, OPTIMIZED_BUFFER_SIZES
from logger import get_logger

# Module logger
log = get_logger("acq_thread")

# Minimum interval between GUI updates (ms)
MIN_GUI_UPDATE_INTERVAL_MS = 50  # 20 FPS max to prevent Qt signal queue backup


# ----- HARDWARE ACQUISITION THREAD -----
# Polls DMA buffer, reads data, emits Qt signals to GUI thread

class AcquisitionThread(QThread):
    """
    Data acquisition thread for PCIe-7821.

    Runs in a separate thread to avoid blocking the GUI.
    Uses Qt signals to communicate data to the main thread.
    """

    # Signals
    data_ready = pyqtSignal(np.ndarray, int, int)  # data, data_type, channel_num
    phase_data_ready = pyqtSignal(np.ndarray, int)  # phase_data, channel_num
    monitor_data_ready = pyqtSignal(np.ndarray, int)  # monitor_data, channel_num
    buffer_status = pyqtSignal(int, int)  # points_in_buffer, buffer_size_mb
    error_occurred = pyqtSignal(str)  # error message
    acquisition_started = pyqtSignal()
    acquisition_stopped = pyqtSignal()

    def __init__(self, api: PCIe7821API, parent=None):
        """
        Initialize acquisition thread.

        Args:
            api: PCIe7821API instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self.api = api
        self._running = False
        self._paused = False

        # Parameters (will be set before starting)
        self._params: Optional[AllParams] = None
        self._total_point_num = 0
        self._point_num_after_merge = 0
        self._frame_num = 20
        self._channel_num = 1
        self._data_source = DataSource.PHASE

        # Thread synchronization
        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()

        # Statistics
        self._frames_acquired = 0
        self._bytes_acquired = 0
        self._loop_count = 0
        self._last_log_time = 0

        # GUI throttling: store latest data, only emit when MIN_GUI_UPDATE_INTERVAL_MS
        # has elapsed. Older pending data is discarded (keeps only latest snapshot).
        self._last_gui_update_time = 0
        self._pending_phase_data = None
        self._pending_raw_data = None
        self._pending_monitor_data = None

        # Dynamic polling: switch between fast/slow intervals based on buffer fill.
        # Hysteresis between high/low thresholds prevents oscillation.
        self._current_polling_interval = POLLING_CONFIG['low_freq_interval_ms'] / 1000.0
        self._high_freq_interval = POLLING_CONFIG['high_freq_interval_ms'] / 1000.0
        self._low_freq_interval = POLLING_CONFIG['low_freq_interval_ms'] / 1000.0
        self._buffer_threshold_high = POLLING_CONFIG['buffer_threshold_high']
        self._buffer_threshold_low = POLLING_CONFIG['buffer_threshold_low']

        log.info("AcquisitionThread initialized with dynamic polling")

    def configure(self, params: AllParams):
        """
        Configure acquisition parameters.

        Args:
            params: Configuration parameters
        """
        self._params = params
        self._total_point_num = params.basic.point_num_per_scan
        self._point_num_after_merge = self._total_point_num // params.phase_demod.merge_point_num
        self._frame_num = params.display.frame_num
        self._channel_num = params.upload.channel_num
        self._data_source = params.upload.data_source

        log.info(f"Configured: total_points={self._total_point_num}, "
                 f"points_after_merge={self._point_num_after_merge}, "
                 f"frames={self._frame_num}, channels={self._channel_num}, "
                 f"data_source={self._data_source}")

    def run(self):
        """Thread main loop"""
        log.info("=== Acquisition thread started ===")
        self._running = True
        self._frames_acquired = 0
        self._bytes_acquired = 0
        self._loop_count = 0
        self._last_log_time = time.time()

        self.acquisition_started.emit()
        log.debug("acquisition_started signal emitted")

        try:
            while self._running:
                self._loop_count += 1
                loop_start = time.perf_counter()

                # Periodic status log (every 5 seconds)
                now = time.time()
                if now - self._last_log_time > 5.0:
                    log.info(f"Status: loops={self._loop_count}, frames={self._frames_acquired}, "
                             f"bytes={self._bytes_acquired/1024/1024:.1f}MB")
                    self._last_log_time = now

                # Check for pause
                self._mutex.lock()
                while self._paused and self._running:
                    log.debug("Thread paused, waiting...")
                    self._pause_condition.wait(self._mutex)
                self._mutex.unlock()

                if not self._running:
                    log.info("Thread stopping (running=False after pause check)")
                    break

                # Determine expected data size
                if self._data_source == DataSource.PHASE:
                    expected_points = self._point_num_after_merge * self._frame_num
                else:
                    expected_points = self._total_point_num * self._frame_num

                log.debug(f"Loop {self._loop_count}: waiting for {expected_points} points")

                # Wait for enough data in buffer with dynamic polling
                wait_start = time.perf_counter()
                wait_count = 0
                while self._running:
                    query_start = time.perf_counter()
                    try:
                        points_in_buffer = self.api.query_buffer_points()
                        query_time = (time.perf_counter() - query_start) * 1000

                        if query_time > 50:
                            log.warning(f"Slow query_buffer_points: {query_time:.1f}ms")

                        # Emit buffer status (throttled)
                        if wait_count % 100 == 0:
                            buffer_mb = points_in_buffer * self._channel_num * 2 // (1024 * 1024)
                            self.buffer_status.emit(points_in_buffer, buffer_mb)

                        if points_in_buffer >= expected_points:
                            wait_time = (time.perf_counter() - wait_start) * 1000
                            log.debug(f"Buffer ready: {points_in_buffer} points, waited {wait_time:.1f}ms ({wait_count} iterations)")
                            break

                        # Dynamic polling interval adjustment
                        self._adjust_polling_interval(points_in_buffer, expected_points)
                        time.sleep(self._current_polling_interval)
                        wait_count += 1

                        if wait_count > 5000:  # 5 second timeout
                            log.error(f"Timeout waiting for data! points_in_buffer={points_in_buffer}, expected={expected_points}")
                            self.error_occurred.emit("Timeout waiting for data")
                            break
                    except Exception as e:
                        log.warning(f"Error querying buffer: {e}")
                        # Check if we should stop
                        if not self._running:
                            log.info("Thread stopping due to stop request during buffer query")
                            break
                        time.sleep(self._current_polling_interval)
                        wait_count += 1

                if not self._running:
                    log.info("Thread stopping (running=False after wait loop)")
                    break

                # Read data
                try:
                    read_start = time.perf_counter()
                    if self._data_source == DataSource.PHASE:
                        self._read_phase_data()
                    else:
                        self._read_raw_data()
                    read_time = (time.perf_counter() - read_start) * 1000
                    log.debug(f"Data read completed in {read_time:.1f}ms")

                except PCIe7821Error as e:
                    log.error(f"Read error: {e}")
                    self.error_occurred.emit(str(e))
                    time.sleep(0.1)
                    continue
                except Exception as e:
                    log.error(f"Unexpected read error: {e}")
                    # Check if we should stop
                    if not self._running:
                        log.info("Thread stopping due to stop request during read error")
                        break
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
        """Read raw IQ data"""
        points_per_ch = self._total_point_num * self._frame_num
        log.debug(f"Reading raw data: {points_per_ch} points/ch, {self._channel_num} channels")

        try:
            data, points_returned = self.api.read_data(points_per_ch, self._channel_num)
        except Exception as e:
            log.error(f"Failed to read raw data: {e}")
            raise

        self._bytes_acquired += len(data) * 2  # short = 2 bytes

        # Reshape data by channels
        if self._channel_num > 1:
            # Data is interleaved: ch0[0], ch1[0], ch0[1], ch1[1], ...
            data = data.reshape(-1, self._channel_num)

        # Throttle GUI updates to prevent signal queue backup
        self._pending_raw_data = (data, self._data_source, self._channel_num)
        self._emit_if_ready()

    def _read_phase_data(self):
        """Read phase demodulated data"""
        points_per_ch = self._point_num_after_merge * self._frame_num
        log.debug(f"Reading phase data: {points_per_ch} points/ch, {self._channel_num} channels")

        try:
            phase_data, points_returned = self.api.read_phase_data(points_per_ch, self._channel_num)
        except Exception as e:
            log.error(f"Failed to read phase data: {e}")
            raise

        self._bytes_acquired += len(phase_data) * 4  # int = 4 bytes

        # Reshape data by channels
        if self._channel_num > 1:
            phase_data = phase_data.reshape(-1, self._channel_num)

        # Store pending data for throttled emission
        self._pending_phase_data = (phase_data, self._channel_num)

        # Also read monitor data when in phase mode
        try:
            monitor_data = self.api.read_monitor_data(
                self._point_num_after_merge, self._channel_num
            )
            self._pending_monitor_data = (monitor_data, self._channel_num)
        except PCIe7821Error as e:
            log.warning(f"Monitor data read failed (non-critical): {e}")
        except Exception as e:
            log.warning(f"Monitor data read failed (non-critical): {e}")

        # Emit all pending data if enough time has passed
        self._emit_if_ready()

    def _emit_if_ready(self):
        """Emit pending data signals if enough time has passed since last update"""
        current_time = time.perf_counter() * 1000  # ms
        elapsed = current_time - self._last_gui_update_time

        if elapsed < MIN_GUI_UPDATE_INTERVAL_MS:
            # Not enough time passed, skip this update (keep latest data pending)
            return

        # Emit all pending signals
        signals_emitted = 0

        if self._pending_phase_data is not None:
            phase_data, channel_num = self._pending_phase_data
            log.debug(f"Emitting phase_data_ready signal: shape={phase_data.shape}")
            self.phase_data_ready.emit(phase_data, channel_num)
            self._pending_phase_data = None
            signals_emitted += 1

        if self._pending_raw_data is not None:
            data, data_source, channel_num = self._pending_raw_data
            log.debug(f"Emitting data_ready signal: shape={data.shape}, dtype={data.dtype}")
            self.data_ready.emit(data, data_source, channel_num)
            self._pending_raw_data = None
            signals_emitted += 1

        if self._pending_monitor_data is not None:
            monitor_data, channel_num = self._pending_monitor_data
            log.debug(f"Emitting monitor_data_ready signal: shape={monitor_data.shape}")
            self.monitor_data_ready.emit(monitor_data, channel_num)
            self._pending_monitor_data = None
            signals_emitted += 1

        if signals_emitted > 0:
            self._last_gui_update_time = current_time
            log.debug(f"GUI update: emitted {signals_emitted} signals, elapsed={elapsed:.1f}ms")

    def _adjust_polling_interval(self, points_in_buffer: int, expected_points: int):
        """Adjust polling interval based on buffer usage"""
        if expected_points == 0:
            return

        buffer_usage_ratio = points_in_buffer / expected_points

        if buffer_usage_ratio >= self._buffer_threshold_high:
            # High buffer usage - use high frequency polling
            self._current_polling_interval = self._high_freq_interval
        elif buffer_usage_ratio <= self._buffer_threshold_low:
            # Low buffer usage - use low frequency polling
            self._current_polling_interval = self._low_freq_interval
        # else: keep current interval (hysteresis)

        # Log interval changes (throttled)
        if self._loop_count % 100 == 0:
            log.debug(f"Buffer usage: {buffer_usage_ratio:.1%}, polling interval: {self._current_polling_interval*1000:.1f}ms")

    def stop(self):
        """Stop acquisition thread"""
        log.info("Stop requested")
        self._running = False

        # Wake up if paused
        self._mutex.lock()
        self._paused = False
        self._pause_condition.wakeAll()
        self._mutex.unlock()

        # Wait for thread to finish
        if self.isRunning():
            log.debug("Waiting for thread to finish...")
            if not self.wait(3000):  # 3 second timeout
                log.warning("Thread did not finish in 3 seconds! Terminating forcefully...")
                self.terminate()
                # Wait a bit more for cleanup
                if not self.wait(1000):
                    log.error("Thread termination failed!")
                else:
                    log.info("Thread terminated successfully")
            else:
                log.debug("Thread finished gracefully")

    def pause(self):
        """Pause acquisition"""
        log.info("Pause requested")
        self._mutex.lock()
        self._paused = True
        self._mutex.unlock()

    def resume(self):
        """Resume acquisition"""
        log.info("Resume requested")
        self._mutex.lock()
        self._paused = False
        self._pause_condition.wakeAll()
        self._mutex.unlock()

    @property
    def is_running(self) -> bool:
        """Check if acquisition is running"""
        return self._running and self.isRunning()

    @property
    def is_paused(self) -> bool:
        """Check if acquisition is paused"""
        return self._paused

    @property
    def frames_acquired(self) -> int:
        """Get number of frames acquired"""
        return self._frames_acquired

    @property
    def bytes_acquired(self) -> int:
        """Get total bytes acquired"""
        return self._bytes_acquired

    @property
    def point_num_after_merge(self) -> int:
        """Get points per scan after merge"""
        return self._point_num_after_merge

    @property
    def total_point_num(self) -> int:
        """Get total points per scan"""
        return self._total_point_num


# ----- SIMULATED ACQUISITION THREAD -----
# Generates random data for UI testing without hardware

class SimulatedAcquisitionThread(AcquisitionThread):
    """
    Simulated acquisition thread for testing without hardware.
    """

    def __init__(self, parent=None):
        """Initialize with dummy API"""
        log.info("Creating SimulatedAcquisitionThread")

        # Create a mock API
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
        """Simulated acquisition loop"""
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
                loop_start = time.perf_counter()

                # Periodic status log
                now = time.time()
                if now - self._last_log_time > 5.0:
                    log.info(f"Simulation status: loops={self._loop_count}, frames={self._frames_acquired}")
                    self._last_log_time = now

                # Check for pause
                self._mutex.lock()
                while self._paused and self._running:
                    self._pause_condition.wait(self._mutex)
                self._mutex.unlock()

                if not self._running:
                    break

                # Simulate acquisition delay based on scan rate
                scan_rate = self._params.basic.scan_rate if self._params else 2000
                delay = self._frame_num / max(scan_rate, 1)
                time.sleep(delay)

                # Generate simulated data
                if self._data_source == DataSource.PHASE:
                    points = self._point_num_after_merge * self._frame_num
                    phase_data = np.random.randint(-100000, 100000, points * self._channel_num, dtype=np.int32)

                    if self._channel_num > 1:
                        phase_data = phase_data.reshape(-1, self._channel_num)

                    # Use throttled emission (same as real acquisition)
                    self._pending_phase_data = (phase_data, self._channel_num)
                    self._bytes_acquired += len(phase_data.flatten()) * 4

                    # Simulated monitor data
                    monitor_data = np.random.randint(0, 65535, self._point_num_after_merge * self._channel_num, dtype=np.uint32)
                    self._pending_monitor_data = (monitor_data, self._channel_num)
                else:
                    points = self._total_point_num * self._frame_num
                    data = np.random.randint(-32768, 32767, points * self._channel_num, dtype=np.int16)

                    if self._channel_num > 1:
                        data = data.reshape(-1, self._channel_num)

                    # Use throttled emission (same as real acquisition)
                    self._pending_raw_data = (data, self._data_source, self._channel_num)
                    self._bytes_acquired += len(data.flatten()) * 2

                # Emit pending signals if enough time has passed
                self._emit_if_ready()

                # Emit buffer status (throttle this too - only every 10 loops)
                if self._loop_count % 10 == 0:
                    self.buffer_status.emit(100000, 10)

                self._frames_acquired += self._frame_num

                loop_time = (time.perf_counter() - loop_start) * 1000
                log.debug(f"Simulation loop {self._loop_count}: {loop_time:.1f}ms")

        except Exception as e:
            log.exception(f"Simulation error: {e}")
            self.error_occurred.emit(f"Simulation error: {e}")

        finally:
            log.info(f"=== Simulated acquisition thread stopped === (loops={self._loop_count})")
            self.acquisition_stopped.emit()
