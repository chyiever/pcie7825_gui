"""
WFBG-7825 FFT Worker Thread Module.

Run FFT/PSD calculations off the GUI thread for both Raw and Phase displays.
"""

import gc
import time

import numpy as np
from PyQt5.QtCore import QMutex, QThread, pyqtSignal

from logger import get_logger
from spectrum_analyzer import RealTimeSpectrumAnalyzer, WindowType

log = get_logger("fft_worker")


class FFTWorkerThread(QThread):
    """Background worker for FFT/PSD calculations."""

    fft_ready = pyqtSignal(object, object, float, float, str, bool)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spectrum_analyzer = RealTimeSpectrumAnalyzer(WindowType.HANNING)

        self._mutex = QMutex()
        self._pending_data = None
        self._sample_rate = 1e9
        self._psd_mode = False
        self._data_type = 'short'
        self._running = False

        log.info("FFTWorkerThread initialized")

    def calculate_fft(
        self,
        data: np.ndarray,
        psd_mode: bool = False,
        sample_rate: float = None,
        data_type: str = 'short',
    ):
        """Queue a one-shot FFT/PSD calculation."""
        if data is None or len(data) < 2:
            return

        self._mutex.lock()
        try:
            max_fft_points = min(len(data), 65536)
            self._pending_data = data[:max_fft_points].copy()
            if sample_rate is not None:
                self._sample_rate = float(sample_rate)
            self._psd_mode = bool(psd_mode)
            self._data_type = 'int' if data_type == 'int' else 'short'

            if not self.isRunning():
                self._running = True
                self.start()
                log.debug(
                    f"FFT calculation requested, using {max_fft_points} points, "
                    f"sample_rate={self._sample_rate}, data_type={self._data_type}, thread started"
                )
            else:
                log.debug(
                    f"FFT calculation requested, using {max_fft_points} points, "
                    f"sample_rate={self._sample_rate}, data_type={self._data_type}, data updated"
                )
        finally:
            self._mutex.unlock()

    def run(self):
        """Process the latest pending FFT request."""
        log.info("FFT worker thread started")

        try:
            self._mutex.lock()
            data = self._pending_data
            sample_rate = self._sample_rate
            psd_mode = self._psd_mode
            data_type = self._data_type
            self._pending_data = None
            self._mutex.unlock()

            if data is not None:
                start_time = time.perf_counter()
                freq, spectrum, df = self.spectrum_analyzer.update(
                    data, sample_rate, psd_mode, data_type
                )

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                log.debug(
                    f"FFT calculation completed in {elapsed_ms:.1f}ms, data size: {len(data)}, "
                    f"sample_rate={sample_rate}, data_type={data_type}"
                )

                self.fft_ready.emit(freq, spectrum, df, sample_rate, data_type, psd_mode)

                del data
                gc.collect()

        except Exception as e:
            log.exception(f"FFT calculation error: {e}")
            self.error_occurred.emit(f"FFT calculation failed: {e}")

        finally:
            self._running = False
            log.info("FFT worker thread finished")

    def stop(self):
        """Stop the worker and discard any pending request."""
        self._mutex.lock()
        self._running = False
        self._pending_data = None
        self._mutex.unlock()

        if self.isRunning():
            self.wait(2000)
            if self.isRunning():
                log.warning("FFT thread did not finish, terminating...")
                self.terminate()
                self.wait(1000)

        log.info("FFT worker thread stopped")

    def set_window_type(self, window_type: WindowType):
        """Update the window function used by the analyzer."""
        self.spectrum_analyzer.set_window(window_type)
        log.debug(f"FFT window type changed to {window_type}")

    def reset_analyzer(self):
        """Clear temporal averaging before a new acquisition session."""
        self.spectrum_analyzer.reset()
