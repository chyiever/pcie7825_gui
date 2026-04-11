#!/usr/bin/env python
"""
Build the WFBG-7825 GUI into a standalone Windows executable.

Default behavior:
    python build_exe.py

Common variants:
    python build_exe.py --console
    python build_exe.py --clean-only
    python build_exe.py --skip-clean
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence


APP_NAME = "eDASread"
PROJECT_ROOT = Path(__file__).resolve().parent
ENTRY_SCRIPT = PROJECT_ROOT / "run.py"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use PyInstaller to package the project into a standalone exe."
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Build a console-mode executable for debugging.",
    )
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        help="Do not remove previous build/dist/spec outputs before packaging.",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only clean old packaging outputs and then exit.",
    )
    parser.add_argument(
        "--name",
        default=APP_NAME,
        help=f"Executable name. Default: {APP_NAME}",
    )
    parser.add_argument(
        "--distpath",
        default=str(DIST_DIR),
        help=f"PyInstaller dist directory. Default: {DIST_DIR}",
    )
    parser.add_argument(
        "--workpath",
        default=str(BUILD_DIR),
        help=f"PyInstaller build directory. Default: {BUILD_DIR}",
    )
    parser.add_argument(
        "--specpath",
        default=str(PROJECT_ROOT),
        help=f"Directory used to store the generated spec file. Default: {PROJECT_ROOT}",
    )
    parser.add_argument(
        "--upx-dir",
        default=None,
        help="Optional UPX directory path passed through to PyInstaller.",
    )
    return parser.parse_args()


def remove_path(path: Path) -> None:
    if not path.exists():
        return

    if path.is_dir():
        shutil.rmtree(path)
        print(f"[clean] Removed directory: {path}")
        return

    path.unlink()
    print(f"[clean] Removed file: {path}")


def clean_outputs(app_name: str, distpath: Path, workpath: Path, specpath: Path) -> None:
    spec_file = specpath / f"{app_name}.spec"
    for target in (distpath, workpath, spec_file):
        remove_path(target)


def ensure_entry_script() -> None:
    if not ENTRY_SCRIPT.exists():
        raise FileNotFoundError(f"Entry script not found: {ENTRY_SCRIPT}")


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "PyInstaller is not installed. Install it first with:\n"
            "    pip install pyinstaller"
        ) from exc


def add_data_arg(source: Path, destination: str) -> str:
    separator = ";" if os.name == "nt" else ":"
    return f"{source}{separator}{destination}"


def collect_data_files() -> List[str]:
    data_args: List[str] = []
    candidates = [
        (PROJECT_ROOT / "resources", "resources", True),
        (PROJECT_ROOT / "libs", "libs", True),
        (PROJECT_ROOT / "last_params.json", ".", False),
    ]

    for source, destination, required in candidates:
        if source.exists():
            data_args.append(add_data_arg(source, destination))
        elif required:
            raise FileNotFoundError(f"Required packaging resource not found: {source}")

    return data_args


def build_hidden_imports() -> List[str]:
    return [
        "main",
        "main_window",
        "logger",
        "config",
        "wfbg7825_api",
        "acquisition_thread",
        "spectrum_analyzer",
        "fft_worker",
        "time_space_plot",
        "storage",
        "storage.models",
        "storage.manager",
        "storage.file_namer",
        "storage.writer",
        "numpy",
        "pyqtgraph",
        "psutil",
    ]


def build_excluded_modules() -> List[str]:
    return [
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PySide2",
        "PySide2.QtCore",
        "PySide2.QtGui",
        "PySide2.QtWidgets",
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ]


def build_pyinstaller_command(args: argparse.Namespace) -> List[str]:
    distpath = Path(args.distpath).resolve()
    workpath = Path(args.workpath).resolve()
    specpath = Path(args.specpath).resolve()
    src_path = (PROJECT_ROOT / "src").resolve()

    command: List[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        args.name,
        "--distpath",
        str(distpath),
        "--workpath",
        str(workpath),
        "--specpath",
        str(specpath),
        "--paths",
        str(src_path),
    ]

    if not args.console:
        command.append("--windowed")

    if args.upx_dir:
        command.extend(["--upx-dir", str(Path(args.upx_dir).resolve())])

    for data_arg in collect_data_files():
        command.extend(["--add-data", data_arg])

    for hidden_import in build_hidden_imports():
        command.extend(["--hidden-import", hidden_import])

    for excluded_module in build_excluded_modules():
        command.extend(["--exclude-module", excluded_module])

    command.append(str(ENTRY_SCRIPT))
    return command


def run_command(command: Sequence[str]) -> None:
    print("[build] Running command:")
    print("        " + " ".join(f'"{part}"' if " " in part else part for part in command))
    subprocess.run(command, cwd=str(PROJECT_ROOT), check=True)


def expected_output_path(app_name: str, distpath: Path) -> Path:
    return distpath / f"{app_name}.exe"


def print_summary(exe_path: Path) -> None:
    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print()
    print("[done] Packaging completed.")
    print(f"[done] EXE path: {exe_path}")
    print(f"[done] EXE size: {size_mb:.2f} MB")
    print("[done] The generated executable can run on Windows machines without a local Python installation.")


def main() -> int:
    args = parse_args()

    if os.name != "nt":
        print("[warn] This script is intended for Windows packaging. Current platform is not Windows.")

    ensure_entry_script()
    ensure_pyinstaller()

    distpath = Path(args.distpath).resolve()
    workpath = Path(args.workpath).resolve()
    specpath = Path(args.specpath).resolve()

    if not args.skip_clean:
        clean_outputs(args.name, distpath, workpath, specpath)

    if args.clean_only:
        print("[done] Clean-only mode finished.")
        return 0

    command = build_pyinstaller_command(args)
    run_command(command)

    exe_path = expected_output_path(args.name, distpath)
    if not exe_path.exists():
        raise FileNotFoundError(f"Packaging finished but exe was not found: {exe_path}")

    print_summary(exe_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
