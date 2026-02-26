"""
PCIe-7821 Data Saver Module

Asynchronous data saving with queue-based buffering.
Saves original phase data as 32-bit signed int binary (no rad conversion).

Architecture: Producer (acq thread) -> Queue -> Consumer (save thread) -> Disk
Non-blocking: queue.put_nowait() drops data if full to avoid backpressure.

Classes:
- DataSaver: Base async saver with single-file output
- FrameBasedFileSaver: Auto-splits files after N frames (primary)
- TimedFileSaver: Auto-splits files by time interval (legacy)
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


# ----- BASE DATA SAVER -----
# Single-file async saver: data queued from producer, written by background thread

class DataSaver:
    """
    Asynchronous data saver with queue-based buffering.

    Saves data to binary files in the format: {seq}-{HH}-{MM}-{SS}-{scan_rate}.bin
    Example: 1-12-30-45-2000.bin
    """

    def __init__(self, save_path: str = "save_data", buffer_size: int = 100):
        """
        Initialize data saver.

        Args:
            save_path: Directory to save files
            buffer_size: Maximum number of data blocks in queue
        """
        self.save_path = Path(save_path)
        self.buffer_size = buffer_size

        self._data_queue: queue.Queue = queue.Queue(maxsize=buffer_size)
        self._save_thread: Optional[threading.Thread] = None
        self._running = False
        self._file_handle = None
        self._file_no = 0
        self._current_filename = ""
        self._scan_rate = 2000  # Default scan rate

        # Statistics
        self._bytes_written = 0
        self._blocks_written = 0
        self._dropped_blocks = 0

    def start(self, file_no: Optional[int] = None, scan_rate: int = 2000) -> str:
        """
        Start data saving.

        Args:
            file_no: Optional file number. If None, auto-increment.
            scan_rate: Scan rate in Hz for filename

        Returns:
            The filename being written to
        """
        if self._running:
            return self._current_filename

        # Ensure save directory exists
        self.save_path.mkdir(parents=True, exist_ok=True)

        # Set file number
        if file_no is not None:
            self._file_no = file_no
        else:
            self._file_no += 1

        self._scan_rate = scan_rate

        # Create filename with timestamp and scan rate
        # Format: seq-HH-MM-SS-scanrate.bin
        now = datetime.now()
        self._current_filename = f"{self._file_no}-{now.hour:02d}-{now.minute:02d}-{now.second:02d}-{scan_rate}.bin"

        # Open file
        filepath = self.save_path / self._current_filename
        self._file_handle = open(filepath, 'wb')

        log.info(f"Started saving to {filepath}")

        # Reset statistics
        self._bytes_written = 0
        self._blocks_written = 0
        self._dropped_blocks = 0

        # Clear queue
        while not self._data_queue.empty():
            try:
                self._data_queue.get_nowait()
            except queue.Empty:
                break

        # Start save thread
        self._running = True
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

        return self._current_filename

    def stop(self):
        """Stop data saving and close file"""
        if not self._running:
            return

        self._running = False

        # Wait for save thread to finish
        if self._save_thread is not None:
            # Put sentinel to wake up thread
            try:
                self._data_queue.put(None, timeout=0.1)
            except queue.Full:
                pass

            self._save_thread.join(timeout=2.0)
            self._save_thread = None

        # Flush remaining data
        while not self._data_queue.empty():
            try:
                data = self._data_queue.get_nowait()
                if data is not None and self._file_handle is not None:
                    self._write_data(data)
            except queue.Empty:
                break

        # Close file
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None

        log.info(f"Stopped saving. Bytes written: {self._bytes_written}, "
                 f"Blocks: {self._blocks_written}, Dropped: {self._dropped_blocks}")

    def save(self, data: np.ndarray) -> bool:
        """
        Queue data for saving.

        Args:
            data: NumPy array to save (original int32 phase data, no rad conversion applied)

        Returns:
            True if data was queued, False if queue is full
        """
        if not self._running:
            return False

        try:
            # Ensure data is int32 (32-bit signed int) for phase data
            if data.dtype != np.int32:
                data = data.astype(np.int32)

            self._data_queue.put_nowait(data.tobytes())
            return True
        except queue.Full:
            self._dropped_blocks += 1
            return False

    def _save_loop(self):
        """Background thread for saving data"""
        while self._running:
            try:
                data = self._data_queue.get(timeout=0.1)
                if data is None:  # Sentinel
                    continue
                self._write_data(data)
            except queue.Empty:
                continue
            except Exception as e:
                log.error(f"DataSaver error: {e}")

    def _write_data(self, data: bytes):
        """Write data to file"""
        if self._file_handle is not None:
            self._file_handle.write(data)
            self._bytes_written += len(data)
            self._blocks_written += 1

    @property
    def is_running(self) -> bool:
        """Check if saver is running"""
        return self._running

    @property
    def bytes_written(self) -> int:
        """Get total bytes written"""
        return self._bytes_written

    @property
    def blocks_written(self) -> int:
        """Get total blocks written"""
        return self._blocks_written

    @property
    def dropped_blocks(self) -> int:
        """Get number of dropped blocks due to queue full"""
        return self._dropped_blocks

    @property
    def queue_size(self) -> int:
        """Get current queue size"""
        return self._data_queue.qsize()

    @property
    def current_filename(self) -> str:
        """Get current filename"""
        return self._current_filename

    @property
    def file_no(self) -> int:
        """Get current file number"""
        return self._file_no

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop()
        return False

    def __del__(self):
        """Destructor"""
        self.stop()


# ----- FRAME-BASED FILE SAVER -----
# Primary saver: splits files after N frames for manageable file sizes.
# Filename: {seq}-eDAS-{rate}Hz-{points}pt-{timestamp}.{ms}.bin

class FrameBasedFileSaver(DataSaver):
    """
    Frame-based file saver that creates new files after N frames.
    Each frame is treated as one data package.

    Filename format: {seq}-eDAS-{rate}Hz-{points}pt-{timestamp}.{ms}.bin
    Example: 00001-eDAS-1000Hz-0162pt-20260126T014051.256.bin
    """

    def __init__(self, save_path: str = "D:/eDAS_DATA",
                 frames_per_file: int = 10,
                 buffer_size: int = 200):
        """
        Initialize frame-based file saver.

        Args:
            save_path: Directory to save files (default D:/eDAS_DATA)
            frames_per_file: Number of frames per file (default 10)
            buffer_size: Maximum number of data blocks in queue (increased to 200)
        """
        super().__init__(save_path, buffer_size)
        self.frames_per_file = frames_per_file
        self._frame_count = 0
        self._total_bytes_all_files = 0
        self._total_files_created = 0
        self._scan_rate = 2000
        self._points_per_frame = 0
        self._frames_per_file = frames_per_file

    def start(self, file_no: Optional[int] = None, scan_rate: int = 2000,
              points_per_frame: int = 0) -> str:
        """Start saving with frame-based splitting capability"""
        if self._running:
            return self._current_filename

        # Ensure save directory exists
        self.save_path.mkdir(parents=True, exist_ok=True)

        # Set file number
        if file_no is not None:
            self._file_no = file_no
        else:
            self._file_no += 1

        self._scan_rate = scan_rate
        self._points_per_frame = points_per_frame
        self._frame_count = 0
        self._total_files_created = 1

        # Create filename: seq-eDAS-rateHz-pointspt-timestamp.ms.bin
        self._current_filename = self._generate_filename()

        # Open file
        filepath = self.save_path / self._current_filename
        self._file_handle = open(filepath, 'wb')

        log.info(f"Started frame-based saving to {filepath}")

        # Reset statistics
        self._bytes_written = 0
        self._blocks_written = 0
        self._dropped_blocks = 0

        # Clear queue
        while not self._data_queue.empty():
            try:
                self._data_queue.get_nowait()
            except queue.Empty:
                break

        # Start save thread
        self._running = True
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

        return self._current_filename

    def save_frame(self, frame_data: np.ndarray) -> bool:
        """
        Save one frame of data and check for file splitting.

        Args:
            frame_data: Frame data array

        Returns:
            True if frame was saved successfully
        """
        if not self._running:
            return False

        # Save the frame
        success = self.save(frame_data)

        if success:
            self._frame_count += 1
            log.debug(f"Saved frame {self._frame_count}/{self.frames_per_file}")

            # Check if need to create new file
            if self._frame_count >= self.frames_per_file:
                self._split_file()

        return success

    def _generate_filename(self) -> str:
        """Generate filename with new format"""
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%dT%H%M%S")
        milliseconds = int((now.timestamp() % 1) * 1000)

        filename = (f"{self._file_no:05d}-eDAS-{self._scan_rate:04d}Hz-"
                   f"{self._points_per_frame:04d}pt-{timestamp_str}.{milliseconds:03d}.bin")

        return filename

    def _split_file(self):
        """Close current file and open new one"""
        # Update total bytes
        self._total_bytes_all_files += self._bytes_written

        # Close current file
        if self._file_handle is not None:
            self._file_handle.flush()
            self._file_handle.close()

        # Increment file number and create new file
        self._file_no += 1
        self._current_filename = self._generate_filename()

        filepath = self.save_path / self._current_filename
        self._file_handle = open(filepath, 'wb')
        self._bytes_written = 0
        self._frame_count = 0
        self._total_files_created += 1

        log.info(f"Split to new file: {self._current_filename} (File #{self._total_files_created})")

    def stop(self):
        """Stop and update total statistics"""
        self._total_bytes_all_files += self._bytes_written
        super().stop()
        log.info(f"Total files created: {self._total_files_created}, "
                 f"Total frames saved: {(self._total_files_created - 1) * self.frames_per_file + self._frame_count}, "
                 f"Total bytes: {self._total_bytes_all_files}")

    @property
    def total_bytes_all_files(self) -> int:
        """Get total bytes written across all files"""
        return self._total_bytes_all_files + self._bytes_written

    @property
    def total_files_created(self) -> int:
        """Get total number of files created"""
        return self._total_files_created

    @property
    def frame_count(self) -> int:
        """Get current frame count in active file"""
        return self._frame_count

    @property
    def frames_per_file(self) -> int:
        """Get frames per file setting"""
        return self._frames_per_file

    @frames_per_file.setter
    def frames_per_file(self, value: int):
        """Set frames per file"""
        self._frames_per_file = value


# ----- TIME-BASED FILE SAVER (LEGACY) -----
# Splits files by wall-clock duration. Kept for backward compatibility.

class TimedFileSaver(DataSaver):
    """
    Legacy data saver that creates new files every N seconds.
    Kept for backward compatibility.

    Filename format: {seq}-{HH}-{MM}-{SS}-{scan_rate}.bin
    Example: 1-12-30-45-2000.bin, 2-12-30-46-2000.bin, ...
    """

    def __init__(self, save_path: str = "save_data",
                 file_duration_s: float = 1.0,
                 buffer_size: int = 100):
        """
        Initialize timed file saver.

        Args:
            save_path: Directory to save files
            file_duration_s: Duration per file in seconds (default 1.0)
            buffer_size: Maximum number of data blocks in queue
        """
        super().__init__(save_path, buffer_size)
        self.file_duration = file_duration_s
        self._file_start_time: float = 0
        self._total_bytes_all_files = 0
        self._total_files_created = 0

    def start(self, file_no: Optional[int] = None, scan_rate: int = 2000) -> str:
        """Start saving with auto-split capability"""
        self._file_start_time = time.time()
        self._total_bytes_all_files = 0
        self._total_files_created = 1
        return super().start(file_no, scan_rate)

    def save(self, data: np.ndarray) -> bool:
        """Save data with auto-split check based on time"""
        if not self._running:
            return False

        # Check if need to create new file (time-based)
        elapsed = time.time() - self._file_start_time
        if elapsed >= self.file_duration:
            self._split_file()

        return super().save(data)

    def _split_file(self):
        """Close current file and open new one"""
        # Update total bytes
        self._total_bytes_all_files += self._bytes_written

        # Close current file
        if self._file_handle is not None:
            self._file_handle.flush()
            self._file_handle.close()

        # Increment file number and create new file
        self._file_no += 1
        now = datetime.now()
        self._current_filename = f"{self._file_no}-{now.hour:02d}-{now.minute:02d}-{now.second:02d}-{self._scan_rate}.bin"

        filepath = self.save_path / self._current_filename
        self._file_handle = open(filepath, 'wb')
        self._bytes_written = 0
        self._file_start_time = time.time()
        self._total_files_created += 1

        log.info(f"Split to new file: {self._current_filename}")

    def stop(self):
        """Stop and update total statistics"""
        self._total_bytes_all_files += self._bytes_written
        super().stop()
        log.info(f"Total files created: {self._total_files_created}, "
                 f"Total bytes: {self._total_bytes_all_files}")

    @property
    def total_bytes_all_files(self) -> int:
        """Get total bytes written across all files"""
        return self._total_bytes_all_files + self._bytes_written

    @property
    def total_files_created(self) -> int:
        """Get total number of files created"""
        return self._total_files_created
