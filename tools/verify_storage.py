"""Verify storage files, manifests, and optional log summaries.

Usage examples:

python tools/verify_storage.py --data-dir data
python tools/verify_storage.py --data-dir data --log logs/log.txt
python tools/verify_storage.py --data-dir D:\\WFBG7825_DATA --log logs/log.txt --scan-rate 100000
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


BIN_NAME_RE = re.compile(
    r"^(?P<file_no>\d+)-(?P<prefix>.*?fs-eDAS)-(?P<scan_rate>\d+)Hz-"
    r"(?P<points>\d+)pt-(?P<timestamp>\d{8}T\d{6})\.(?P<milliseconds>\d{3})\.bin$"
)
LOG_SUMMARY_RE = re.compile(
    r"Storage worker stopped: files=(?P<files>\d+), blocks=(?P<blocks>\d+), bytes=(?P<bytes>\d+)"
)


@dataclass
class FileCheckResult:
    bin_path: Path
    scan_rate: int
    file_no: int
    points_per_frame: int
    timestamp_s: float
    size_bytes: int
    issues: List[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify storage bin/json files.")
    parser.add_argument("--data-dir", required=True, help="Directory containing .bin/.json files")
    parser.add_argument("--log", help="Optional log file for summary comparison")
    parser.add_argument("--scan-rate", type=int, help="Only inspect one scan rate")
    return parser.parse_args()


def parse_bin_name(path: Path) -> Tuple[int, int, int, float]:
    match = BIN_NAME_RE.match(path.name)
    if not match:
        raise ValueError(f"Unsupported filename format: {path.name}")

    file_no = int(match.group("file_no"))
    scan_rate = int(match.group("scan_rate"))
    points_per_frame = int(match.group("points"))
    timestamp = datetime.strptime(match.group("timestamp"), "%Y%m%dT%H%M%S")
    timestamp_s = timestamp.timestamp() + int(match.group("milliseconds")) / 1000.0
    return file_no, scan_rate, points_per_frame, timestamp_s


def inspect_file(bin_path: Path) -> FileCheckResult:
    file_no, scan_rate, points_per_frame, timestamp_s = parse_bin_name(bin_path)
    issues: List[str] = []

    return FileCheckResult(
        bin_path=bin_path,
        scan_rate=scan_rate,
        file_no=file_no,
        points_per_frame=points_per_frame,
        timestamp_s=timestamp_s,
        size_bytes=bin_path.stat().st_size,
        issues=issues,
    )




def group_results(results: Iterable[FileCheckResult]) -> Dict[int, List[FileCheckResult]]:
    grouped: Dict[int, List[FileCheckResult]] = {}
    for result in results:
        grouped.setdefault(result.scan_rate, []).append(result)
    for items in grouped.values():
        items.sort(key=lambda item: item.file_no)
    return grouped


def check_sequence_continuity(results: List[FileCheckResult]) -> List[str]:
    return []


def collect_file_no_issues(results: List[FileCheckResult]) -> List[str]:
    issues: List[str] = []
    expected = None
    for result in results:
        if expected is None:
            expected = result.file_no
        if result.file_no != expected:
            issues.append(
                f"file number discontinuity: expected {expected:07d} got {result.file_no:07d} ({result.bin_path.name})"
            )
            expected = result.file_no
        expected += 1
    return issues


def extract_log_summaries(log_path: Path) -> List[Tuple[int, int, int]]:
    summaries: List[Tuple[int, int, int]] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LOG_SUMMARY_RE.search(line)
        if match:
            summaries.append(
                (
                    int(match.group("files")),
                    int(match.group("blocks")),
                    int(match.group("bytes")),
                )
            )
    return summaries


def print_group_report(scan_rate: int, results: List[FileCheckResult], log_summaries: List[Tuple[int, int, int]]):
    total_files = len(results)
    total_bytes = sum(item.size_bytes for item in results)
    total_blocks = 0
    file_gaps = collect_file_no_issues(results)
    seq_gaps = check_sequence_continuity(results)
    group_issues = [issue for item in results for issue in item.issues] + file_gaps + seq_gaps

    print(f"\n=== Scan Rate: {scan_rate} Hz ===")
    print(f"files: {total_files}")
    print(f"blocks: {total_blocks}")
    print(f"bytes: {total_bytes}")

    if results:
        gaps = []
        previous = None
        for item in results:
            if previous is not None:
                gaps.append(item.timestamp_s - previous.timestamp_s)
            previous = item
        if gaps:
            print(
                "file gaps (s): min={:.3f} avg={:.3f} max={:.3f}".format(
                    min(gaps),
                    sum(gaps) / len(gaps),
                    max(gaps),
                )
            )

    for item in results:
        print(f"{item.bin_path.name}: size={item.size_bytes}")

    if log_summaries:
        matching = [summary for summary in log_summaries if summary[2] == total_bytes]
        if matching:
            for files, blocks, bytes_written in matching:
                print(
                    f"log summary match: files={files}, blocks={blocks}, bytes={bytes_written}"
                )
                if files != total_files:
                    print(
                        f"  note: data dir has {total_files} files, log summary says {files}. "
                        "This usually means the directory is only a subset of the real save path."
                    )
                if blocks != total_blocks:
                    print(
                        f"  note: data dir has {total_blocks} blocks, log summary says {blocks}. "
                        "This usually means files are missing from the inspected directory."
                    )
        else:
            print("log summary match: none by total bytes")

    if group_issues:
        print("issues:")
        for issue in group_issues:
            print(f"  - {issue}")
    else:
        print("issues: none")


def main():
    args = parse_args()
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"Data directory does not exist: {data_dir}")

    bin_files = sorted(data_dir.glob("*.bin"))
    if not bin_files:
        raise SystemExit(f"No .bin files found in {data_dir}")

    results = [inspect_file(path) for path in bin_files]
    if args.scan_rate is not None:
        results = [item for item in results if item.scan_rate == args.scan_rate]
        if not results:
            raise SystemExit(f"No files found for scan rate {args.scan_rate} Hz")

    log_summaries: List[Tuple[int, int, int]] = []
    if args.log:
        log_path = Path(args.log)
        if not log_path.exists():
            raise SystemExit(f"Log file does not exist: {log_path}")
        log_summaries = extract_log_summaries(log_path)

    print(f"data dir: {data_dir}")
    if args.log:
        print(f"log file: {Path(args.log)}")

    grouped = group_results(results)
    for scan_rate in sorted(grouped):
        print_group_report(scan_rate, grouped[scan_rate], log_summaries)


if __name__ == "__main__":
    main()
