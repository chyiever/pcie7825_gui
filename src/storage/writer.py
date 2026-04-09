"""Low-level file writer for acquisition storage."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import FileRecord, StorageBlock, StorageSessionConfig


class BinaryFileWriter:
    """Owns one binary file handle at a time."""

    def __init__(self, base_path: Path, session_config: StorageSessionConfig):
        self._base_path = base_path
        self._session_config = session_config
        self._handle = None
        self._record: Optional[FileRecord] = None

    @property
    def current_record(self) -> Optional[FileRecord]:
        return self._record

    def open(self, file_no: int, filename: str, first_block: StorageBlock) -> FileRecord:
        file_path = self._base_path / filename
        self._handle = open(file_path, "wb")
        self._record = FileRecord(
            file_no=file_no,
            filename=filename,
            path=file_path,
            first_sequence=first_block.sequence_id,
            last_sequence=first_block.sequence_id,
            opened_at_ns=first_block.created_at_ns,
        )
        return self._record

    def write_block(self, block: StorageBlock):
        if self._handle is None or self._record is None:
            raise RuntimeError("BinaryFileWriter is not open")

        self._handle.write(block.payload)
        self._handle.flush()
        self._record.block_count += 1
        self._record.frame_count += block.frames_in_block
        self._record.payload_bytes += block.payload_bytes
        self._record.last_sequence = block.sequence_id

    def close(self, closed_at_ns: int) -> Optional[FileRecord]:
        if self._record is None:
            return None

        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None

        self._record.closed_at_ns = closed_at_ns
        closed_record = self._record
        self._record = None
        return closed_record
