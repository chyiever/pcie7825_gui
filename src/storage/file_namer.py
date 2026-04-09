"""File naming helpers for the storage pipeline."""

from __future__ import annotations

from datetime import datetime

from .models import StorageSessionConfig


def build_data_filename(file_no: int, config: StorageSessionConfig, started_at_ns: int) -> str:
    """Build a deterministic data filename for one storage file."""

    started_at_s = started_at_ns / 1_000_000_000
    started_at = datetime.fromtimestamp(started_at_s)
    timestamp_str = started_at.strftime("%Y%m%dT%H%M%S")
    milliseconds = int((started_at_ns // 1_000_000) % 1000)

    prefix = f"{config.file_prefix}-" if config.file_prefix else ""
    return (
        f"{file_no:07d}-{prefix}fs-eDAS-{config.scan_rate:04d}Hz-"
        f"{config.points_per_frame:04d}pt-{timestamp_str}.{milliseconds:03d}.bin"
    )

