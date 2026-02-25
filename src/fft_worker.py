"""
WFBG-7825 FFT Worker Thread Module

独立线程处理FFT计算，避免GUI阻塞。
专为Raw数据优化，支持3秒间隔更新。
"""

import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal, QMutex
from spectrum_analyzer import RealTimeSpectrumAnalyzer, WindowType
from logger import get_logger

log = get_logger("fft_worker")


class FFTWorkerThread(QThread):
    """FFT计算工作线程"""

    # 信号定义
    fft_ready = pyqtSignal(np.ndarray, np.ndarray, float)  # freq, spectrum, df
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spectrum_analyzer = RealTimeSpectrumAnalyzer(WindowType.HANNING)

        self._mutex = QMutex()
        self._pending_data = None
        self._sample_rate = 1e9  # 1GHz固定采样率
        self._psd_mode = False
        self._running = False

        log.info("FFTWorkerThread initialized")

    def calculate_fft(self, data: np.ndarray, psd_mode: bool = False):
        """
        请求FFT计算

        Args:
            data: 输入数据（单帧，1GHz采样率）
            psd_mode: 是否计算PSD
        """
        self._mutex.lock()
        try:
            self._pending_data = data.copy()  # 安全复制数据
            self._psd_mode = psd_mode

            if not self.isRunning():
                self._running = True
                self.start()
                log.debug("FFT calculation requested, thread started")
            else:
                log.debug("FFT calculation requested, data updated")
        finally:
            self._mutex.unlock()

    def run(self):
        """线程主循环"""
        log.info("FFT worker thread started")

        try:
            self._mutex.lock()
            data = self._pending_data
            psd_mode = self._psd_mode
            self._pending_data = None
            self._mutex.unlock()

            if data is not None:
                start_time = time.perf_counter()

                # 执行FFT计算
                freq, spectrum, df = self.spectrum_analyzer.update(
                    data, self._sample_rate, psd_mode, 'short'
                )

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                log.debug(f"FFT calculation completed in {elapsed_ms:.1f}ms")

                # 发送结果
                self.fft_ready.emit(freq, spectrum, df)

        except Exception as e:
            log.exception(f"FFT calculation error: {e}")
            self.error_occurred.emit(f"FFT calculation failed: {e}")

        finally:
            self._running = False
            log.info("FFT worker thread finished")

    def stop(self):
        """停止FFT计算线程"""
        self._mutex.lock()
        self._running = False
        self._pending_data = None
        self._mutex.unlock()

        if self.isRunning():
            self.wait(2000)  # 等待2秒
            if self.isRunning():
                log.warning("FFT thread did not finish, terminating...")
                self.terminate()
                self.wait(1000)

        log.info("FFT worker thread stopped")

    def set_window_type(self, window_type: WindowType):
        """设置窗函数类型"""
        self.spectrum_analyzer.set_window(window_type)
        log.debug(f"FFT window type changed to {window_type}")