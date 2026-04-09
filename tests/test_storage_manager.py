"""Tests for the dedicated storage pipeline."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage import StorageBlock, StorageManager, StorageSessionConfig


class StorageManagerTest(unittest.TestCase):
    def _make_config(self, save_path: Path) -> StorageSessionConfig:
        return StorageSessionConfig(
            save_path=save_path,
            scan_rate=100000,
            points_per_frame=69,
            channel_count=1,
            data_source=2,
            frames_per_block=10000,
            blocks_per_file=2,
            queue_maxsize=8,
            dtype_name="int32",
            target_frames_per_file=20000,
        )

    def _make_block(self, sequence_id: int, payload_size: int = 69 * 10000 * 4) -> StorageBlock:
        return StorageBlock(
            sequence_id=sequence_id,
            created_at_ns=time.time_ns(),
            frames_in_block=10000,
            points_per_frame=69,
            channel_count=1,
            dtype_name="int32",
            payload=bytes([sequence_id % 251]) * payload_size,
        )

    def test_rotation_creates_expected_bin_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            save_path = Path(tmp_dir)
            manager = StorageManager()
            manager.start_session(self._make_config(save_path))

            for sequence_id in range(5):
                self.assertTrue(manager.submit_block(self._make_block(sequence_id)))

            self.assertTrue(manager.stop(timeout_s=10.0))

            stats = manager.snapshot_stats()
            self.assertEqual(stats.written_blocks, 5)
            self.assertEqual(stats.total_files_created, 3)

            bin_files = sorted(save_path.glob("*.bin"))
            json_files = sorted(save_path.glob("*.json"))
            self.assertEqual(len(bin_files), 3)
            self.assertEqual(len(json_files), 0)

            expected_sizes = [2, 2, 1]
            block_bytes = len(self._make_block(0).payload)
            for path, expected_blocks in zip(bin_files, expected_sizes):
                self.assertEqual(path.stat().st_size, block_bytes * expected_blocks)


    def test_stop_drains_queued_blocks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            save_path = Path(tmp_dir)
            manager = StorageManager()
            manager.start_session(self._make_config(save_path))

            for sequence_id in range(4):
                self.assertTrue(manager.submit_block(self._make_block(sequence_id, payload_size=4096)))

            self.assertTrue(manager.stop(timeout_s=10.0))

            stats = manager.snapshot_stats()
            self.assertEqual(stats.written_blocks, 4)
            self.assertEqual(stats.dropped_blocks, 0)
            self.assertEqual(stats.last_written_sequence, 3)
            self.assertEqual(stats.state, "stopped")


if __name__ == "__main__":
    unittest.main()
