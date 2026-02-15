"""
WFBG-7825 Data Saver Module

Asynchronous data saving with queue-based buffering.
Architecture: Producer (acq thread) -> Queue -> Consumer (save thread) -> Disk
"""

import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import numpy as np

from logger import get_logger

log = get_logger("data_saver")


class DataSaver:
    """Asynchronous data saver with queue-based buffering."""

    def __init__(self, save_path: str = "save_data", buffer_size: int = 100):
        self.save_path = Path(save_path)
        self.buffer_size = buffer_size

        self._data_queue: queue.Queue = queue.Queue(maxsize=buffer_size)
        self._save_thread: Optional[threading.Thread] = None
        self._running = False
        self._file_handle = None
        self._file_no = 0
        self._current_filename = ""
        self._scan_rate = 2000

        self._bytes_written = 0
        self._blocks_written = 0
        self._dropped_blocks = 0

    def start(self, file_no: Optional[int] = None, scan_rate: int = 2000) -> str:
        if self._running:
            return self._current_filename

        self.save_path.mkdir(parents=True, exist_ok=True)

        if file_no is not None:
            self._file_no = file_no
        else:
            self._file_no += 1

        self._scan_rate = scan_rate

        now = datetime.now()
        self._current_filename = f"{self._file_no}-{now.hour:02d}-{now.minute:02d}-{now.second:02d}-{scan_rate}.bin"

        filepath = self.save_path / self._current_filename
        self._file_handle = open(filepath, 'wb')

        log.info(f"Started saving to {filepath}")

        self._bytes_written = 0
        self._blocks_written = 0
        self._dropped_blocks = 0

        while not self._data_queue.empty():
            try:
                self._data_queue.get_nowait()
            except queue.Empty:
                break

        self._running = True
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

        return self._current_filename

    def stop(self):
        if not self._running:
            return

        self._running = False

        if self._save_thread is not None:
            try:
                self._data_queue.put(None, timeout=0.1)
            except queue.Full:
                pass
            self._save_thread.join(timeout=2.0)
            self._save_thread = None

        while not self._data_queue.empty():
            try:
                data = self._data_queue.get_nowait()
                if data is not None and self._file_handle is not None:
                    self._write_data(data)
            except queue.Empty:
                break

        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None

        log.info(f"Stopped saving. Bytes written: {self._bytes_written}, "
                 f"Blocks: {self._blocks_written}, Dropped: {self._dropped_blocks}")

    def save(self, data: np.ndarray) -> bool:
        if not self._running:
            return False

        try:
            if data.dtype != np.int32:
                data = data.astype(np.int32)
            self._data_queue.put_nowait(data.tobytes())
            return True
        except queue.Full:
            self._dropped_blocks += 1
            return False

    def _save_loop(self):
        while self._running:
            try:
                data = self._data_queue.get(timeout=0.1)
                if data is None:
                    continue
                self._write_data(data)
            except queue.Empty:
                continue
            except Exception as e:
                log.error(f"DataSaver error: {e}")

    def _write_data(self, data: bytes):
        if self._file_handle is not None:
            self._file_handle.write(data)
            self._bytes_written += len(data)
            self._blocks_written += 1

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    @property
    def blocks_written(self) -> int:
        return self._blocks_written

    @property
    def dropped_blocks(self) -> int:
        return self._dropped_blocks

    @property
    def queue_size(self) -> int:
        return self._data_queue.qsize()

    @property
    def current_filename(self) -> str:
        return self._current_filename

    @property
    def file_no(self) -> int:
        return self._file_no

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def __del__(self):
        self.stop()


class FrameBasedFileSaver(DataSaver):
    """
    Frame-based file saver that creates new files after N frames.
    Filename format: {seq}-wfbg7825-{rate}Hz-{points}pt-{timestamp}.{ms}.bin
    """

    def __init__(self, save_path: str = "D:/WFBG7825_DATA",
                 frames_per_file: int = 10,
                 buffer_size: int = 200):
        super().__init__(save_path, buffer_size)
        self._frames_per_file = frames_per_file
        self._frame_count = 0
        self._total_bytes_all_files = 0
        self._total_files_created = 0
        self._scan_rate = 2000
        self._points_per_frame = 0

    def start(self, file_no: Optional[int] = None, scan_rate: int = 2000,
              points_per_frame: int = 0) -> str:
        if self._running:
            return self._current_filename

        self.save_path.mkdir(parents=True, exist_ok=True)

        if file_no is not None:
            self._file_no = file_no
        else:
            self._file_no += 1

        self._scan_rate = scan_rate
        self._points_per_frame = points_per_frame
        self._frame_count = 0
        self._total_files_created = 1

        self._current_filename = self._generate_filename()

        filepath = self.save_path / self._current_filename
        self._file_handle = open(filepath, 'wb')

        log.info(f"Started frame-based saving to {filepath}")

        self._bytes_written = 0
        self._blocks_written = 0
        self._dropped_blocks = 0

        while not self._data_queue.empty():
            try:
                self._data_queue.get_nowait()
            except queue.Empty:
                break

        self._running = True
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

        return self._current_filename

    def save_frame(self, frame_data: np.ndarray) -> bool:
        if not self._running:
            return False

        success = self.save(frame_data)

        if success:
            self._frame_count += 1
            log.debug(f"Saved frame {self._frame_count}/{self._frames_per_file}")

            if self._frame_count >= self._frames_per_file:
                self._split_file()

        return success

    def _generate_filename(self) -> str:
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%dT%H%M%S")
        milliseconds = int((now.timestamp() % 1) * 1000)

        filename = (f"{self._file_no:05d}-wfbg7825-{self._scan_rate:04d}Hz-"
                   f"{self._points_per_frame:04d}pt-{timestamp_str}.{milliseconds:03d}.bin")
        return filename

    def _split_file(self):
        self._total_bytes_all_files += self._bytes_written

        if self._file_handle is not None:
            self._file_handle.flush()
            self._file_handle.close()

        self._file_no += 1
        self._current_filename = self._generate_filename()

        filepath = self.save_path / self._current_filename
        self._file_handle = open(filepath, 'wb')
        self._bytes_written = 0
        self._frame_count = 0
        self._total_files_created += 1

        log.info(f"Split to new file: {self._current_filename} (File #{self._total_files_created})")

    def stop(self):
        self._total_bytes_all_files += self._bytes_written
        super().stop()
        log.info(f"Total files created: {self._total_files_created}, "
                 f"Total bytes: {self._total_bytes_all_files}")

    @property
    def total_bytes_all_files(self) -> int:
        return self._total_bytes_all_files + self._bytes_written

    @property
    def total_files_created(self) -> int:
        return self._total_files_created

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def frames_per_file(self) -> int:
        return self._frames_per_file

    @frames_per_file.setter
    def frames_per_file(self, value: int):
        self._frames_per_file = value
