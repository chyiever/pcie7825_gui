"""Threaded storage manager with safe file rotation and draining stop."""

from __future__ import annotations

import copy
import queue
import threading
import time
from pathlib import Path
from typing import Optional, Union

from logger import get_logger

from .file_namer import build_data_filename
from .models import StopCommand, StorageBlock, StorageSessionConfig, StorageStats
from .writer import BinaryFileWriter

log = get_logger("storage")

QueueItem = Union[StorageBlock, StopCommand]


class StorageManager:
    """Accepts storage blocks from acquisition and persists them on one worker thread."""

    def __init__(self):
        self._queue: Optional[queue.Queue[QueueItem]] = None
        self._thread: Optional[threading.Thread] = None
        self._config: Optional[StorageSessionConfig] = None
        self._stats = StorageStats()
        self._stats_lock = threading.Lock()
        self._accepting = False
        self._stop_command_sent = False
        self._stop_event = threading.Event()
        self._stopped_event = threading.Event()

    def start_session(self, config: StorageSessionConfig):
        """Create a clean storage session and start the dedicated storage thread."""

        if self.is_running:
            raise RuntimeError("StorageManager is already running")

        config.save_path.mkdir(parents=True, exist_ok=True)

        self._config = config
        self._queue = queue.Queue(maxsize=config.queue_maxsize)
        self._accepting = True
        self._stop_command_sent = False
        self._stop_event.clear()
        self._stopped_event.clear()

        with self._stats_lock:
            self._stats = StorageStats(
                state="starting",
                current_file_no=1,
                started_at_ns=time.time_ns(),
            )

        self._thread = threading.Thread(
            target=self._worker_loop,
            name="StorageWorker",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Storage session started: path=%s, blocks_per_file=%s, queue=%s",
            config.save_path,
            config.blocks_per_file,
            config.queue_maxsize,
        )

    def submit_block(self, block: StorageBlock, timeout_s: float = 1.0) -> bool:
        """Submit one block to the storage thread.

        This method blocks briefly under backpressure instead of silently dropping data.
        """

        if not self._accepting or self._queue is None:
            self._update_last_error("Storage session is not accepting data")
            return False

        deadline = time.perf_counter() + max(timeout_s, 0.0)
        while self._accepting:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            try:
                self._queue.put(block, timeout=min(0.2, remaining))
                with self._stats_lock:
                    self._stats.accepted_blocks += 1
                    self._stats.queue_size = self._queue.qsize()
                return True
            except queue.Full:
                self._update_queue_size()
                log.warning(
                    "Storage queue is full while submitting block #%s (queue=%s/%s)",
                    block.sequence_id,
                    self._queue.qsize(),
                    self._config.queue_maxsize if self._config else "?",
                )

        with self._stats_lock:
            self._stats.dropped_blocks += 1
        self._update_last_error(
            f"Storage queue blocked; failed to submit block #{block.sequence_id}"
        )
        return False

    def request_stop(self):
        """Stop accepting new blocks and ask the worker to drain the queue."""

        if self._queue is None or self._stop_command_sent:
            return

        self._accepting = False
        self._stop_event.set()

        try:
            self._queue.put_nowait(StopCommand())
            self._stop_command_sent = True
        except queue.Full:
            # The worker will still stop after queued blocks drain.
            self._stop_command_sent = True

        with self._stats_lock:
            self._stats.stop_requested = True
            self._stats.state = "draining"
            self._stats.queue_size = self._queue.qsize()

    def stop(self, timeout_s: float = 30.0) -> bool:
        """Public blocking stop used by controller code."""

        self.request_stop()
        return self.wait_until_stopped(timeout_s)

    def wait_until_stopped(self, timeout_s: float = 30.0) -> bool:
        """Wait for the worker to flush and close all files."""

        if self._thread is None:
            return True

        self._thread.join(timeout_s)
        finished = not self._thread.is_alive()
        if finished:
            self._stopped_event.set()
        else:
            self._update_last_error("Timed out while waiting for storage worker to stop")
            log.error("Timed out while waiting for storage worker to stop")
        return finished

    def snapshot_stats(self) -> StorageStats:
        with self._stats_lock:
            stats = copy.deepcopy(self._stats)

        if self._queue is not None:
            stats.queue_size = self._queue.qsize()
        return stats

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_accepting(self) -> bool:
        return self._accepting

    def _worker_loop(self):
        if self._config is None or self._queue is None:
            self._update_last_error("Storage worker started without configuration")
            return

        config = self._config
        writer = BinaryFileWriter(config.save_path, config)
        current_file_no = 1
        pending_rotate = False

        with self._stats_lock:
            self._stats.state = "running"

        try:
            while True:
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    self._update_queue_size()
                    if self._stop_event.is_set() and self._queue.empty():
                        break
                    continue

                try:
                    if isinstance(item, StopCommand):
                        with self._stats_lock:
                            self._stats.state = "draining"
                        if self._queue.empty():
                            break
                        continue

                    if pending_rotate:
                        writer.close(item.created_at_ns)
                        current_file_no += 1
                        pending_rotate = False

                    if writer.current_record is None:
                        filename = build_data_filename(current_file_no, config, item.created_at_ns)
                        writer.open(current_file_no, filename, item)
                        with self._stats_lock:
                            self._stats.current_file_no = current_file_no
                            self._stats.current_filename = filename
                            self._stats.total_files_created += 1
                        log.info("Opened storage file: %s", config.save_path / filename)

                    writer.write_block(item)

                    record = writer.current_record
                    with self._stats_lock:
                        self._stats.written_blocks += 1
                        self._stats.total_bytes += item.payload_bytes
                        self._stats.last_written_sequence = item.sequence_id
                        self._stats.current_file_block_count = record.block_count if record else 0
                        self._stats.queue_size = self._queue.qsize()

                    if record is not None and record.frame_count >= config.target_frames_per_file:
                        pending_rotate = True
                        log.info(
                            "Completed storage file %s with %s frames in %s blocks",
                            record.filename,
                            record.frame_count,
                            record.block_count,
                        )
                finally:
                    self._queue.task_done()

            if writer.current_record is not None:
                writer.close(time.time_ns())

            with self._stats_lock:
                self._stats.state = "stopped"
                self._stats.stopped_at_ns = time.time_ns()
                self._stats.current_file_block_count = 0
                self._stats.queue_size = self._queue.qsize()
            log.info(
                "Storage worker stopped: files=%s, blocks=%s, bytes=%s",
                self._stats.total_files_created,
                self._stats.written_blocks,
                self._stats.total_bytes,
            )
        except Exception as exc:
            self._update_last_error(str(exc))
            with self._stats_lock:
                self._stats.state = "error"
            log.exception("Storage worker crashed: %s", exc)
        finally:
            self._accepting = False
            self._stopped_event.set()

    def _update_last_error(self, message: str):
        with self._stats_lock:
            self._stats.last_error = message

    def _update_queue_size(self):
        if self._queue is None:
            return
        with self._stats_lock:
            self._stats.queue_size = self._queue.qsize()
