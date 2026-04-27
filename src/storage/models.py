"""Typed models for the storage pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StorageSessionConfig:
    """Immutable configuration for one storage session."""

    save_path: Path
    scan_rate: int
    points_per_frame: int
    channel_count: int
    data_source: int
    frames_per_block: int
    blocks_per_file: int
    target_frames_per_file: int
    queue_maxsize: int
    dtype_name: str
    file_prefix: str = ""
    downsample_factor: int = 1


@dataclass(frozen=True)
class StorageBlock:
    """One atomic storage unit emitted by the acquisition pipeline."""

    sequence_id: int
    created_at_ns: int
    frames_in_block: int
    points_per_frame: int
    channel_count: int
    dtype_name: str
    payload: bytes

    @property
    def payload_bytes(self) -> int:
        return len(self.payload)


@dataclass
class StorageStats:
    """Thread-safe snapshot of storage state."""

    state: str = "idle"
    queue_size: int = 0
    accepted_blocks: int = 0
    written_blocks: int = 0
    dropped_blocks: int = 0
    total_bytes: int = 0
    total_files_created: int = 0
    current_file_no: int = 0
    current_file_block_count: int = 0
    current_filename: str = ""
    last_written_sequence: int = -1
    last_error: str = ""
    stop_requested: bool = False
    started_at_ns: int = 0
    stopped_at_ns: int = 0


@dataclass(frozen=True)
class StopCommand:
    """Sentinel consumed by the storage worker to begin draining."""

    reason: str = "stop_requested"


@dataclass
class FileRecord:
    """Per-file runtime summary used while one binary file is open."""

    file_no: int
    filename: str
    path: Path
    first_sequence: int
    last_sequence: int
    block_count: int = 0
    frame_count: int = 0
    payload_bytes: int = 0
    opened_at_ns: int = 0
    closed_at_ns: int = 0
