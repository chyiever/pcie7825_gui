"""
WFBG-7825 DAS Acquisition Software - Main Entry Point

Command-line parsing, logging init, high-DPI support, and app lifecycle.

Usage:
    python main.py                    # Normal mode with hardware
    python main.py --simulate         # Simulation mode for testing
    python main.py --debug            # Enable debug logging
    python main.py --log FILE         # Save log to a custom file
"""

import sys
import argparse
import traceback
import logging
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt

from logger import setup_logging, get_logger, build_default_log_path


def setup_high_dpi():
    """Configure high-DPI display support for modern monitors."""
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def exception_hook(exc_type, exc_value, exc_tb):
    """Global exception handler for unhandled exceptions."""
    log = get_logger("main")
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log.critical(f"Unhandled exception:\n{error_msg}")

    if QApplication.instance():
        QMessageBox.critical(None, "Error", f"An error occurred:\n\n{error_msg}")


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(
        description='WFBG-7825 DAS Acquisition Software',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Normal operation with hardware
  python main.py --simulate         # Testing without hardware
  python main.py --debug            # Debug mode with default local log
  python main.py -s -d -l debug.log # Simulation + debug + custom log
        """
    )

    parser.add_argument('--simulate', '-s', action='store_true',
                        help='Run in simulation mode without hardware')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--log', '-l', type=str, default=None,
                        help='Save log to a custom file path (default: auto local daily log under logs/)')

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    log_file = args.log if args.log else None

    setup_logging(level=log_level, log_file=log_file, console=True)
    log = get_logger("main")
    effective_log_path = Path(log_file).resolve() if log_file else build_default_log_path()

    log.info("=" * 60)
    log.info("WFBG-7825 DAS Acquisition Software Starting")
    log.info(f"Simulation mode: {args.simulate}")
    log.info(f"Debug mode: {args.debug}")
    log.info(f"Log file: {effective_log_path}")
    log.info("=" * 60)

    sys.excepthook = exception_hook

    setup_high_dpi()

    app = QApplication(sys.argv)
    app.setApplicationName("eDAS-fs-7825 gh.26.2.15")
    app.setApplicationVersion("1.0.0")
    app.setStyle('Fusion')

    log.info("QApplication created")

    try:
        log.info("Creating main window...")

        from main_window import MainWindow

        window = MainWindow(simulation_mode=args.simulate)

        if args.simulate:
            window.setWindowTitle("eDAS-fs-7825 gh.26.2.15 [SIMULATION MODE]")

        window.show()
        log.info("Main window shown")

        log.info("Entering event loop...")
        exit_code = app.exec_()
        log.info(f"Event loop exited with code {exit_code}")

        sys.exit(exit_code)

    except Exception as e:
        log.exception(f"Failed to start application: {e}")
        QMessageBox.critical(None, "Startup Error", f"Failed to start application:\n\n{e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
