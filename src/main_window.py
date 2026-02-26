"""
WFBG-7825 Main Window GUI

PyQt5-based GUI with real-time waveform display and parameter control.
Adapted from PCIe-7821 with 7825-specific features:
- FBG peak detection panel (NEW)
- No data_rate, rate2phase, merge, diff, space_avg controls
- Phase data sized by fbg_num_per_ch (not point_num / merge)
- Center freq as ComboBox (80MHz / 200MHz)
- Must run peak detection before start
"""

import sys
import os
import time
import numpy as np
import psutil
import shutil
from typing import Optional
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox, QPushButton, QCheckBox,
    QRadioButton, QButtonGroup, QSpinBox, QDoubleSpinBox, QFileDialog,
    QMessageBox, QStatusBar, QSplitter, QFrame, QSizePolicy, QProgressBar,
    QScrollArea, QTabWidget
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QFont, QPixmap
import pyqtgraph as pg

from config import (
    AllParams, BasicParams, UploadParams, PhaseDemodParams, PeakDetectionParams,
    DisplayParams, SaveParams, TimeSpaceParams,
    ClockSource, TriggerDirection, DataSource, DisplayMode,
    CHANNEL_NUM_OPTIONS, DATA_SOURCE_OPTIONS, CENTER_FREQ_OPTIONS,
    validate_point_num, calculate_fiber_length, calculate_data_rate_mbps,
    OPTIMIZED_BUFFER_SIZES, MONITOR_UPDATE_INTERVALS, RAW_DATA_CONFIG
)
from wfbg7825_api import WFBG7825API, WFBG7825Error
from acquisition_thread import AcquisitionThread, SimulatedAcquisitionThread
from data_saver import FrameBasedFileSaver
from spectrum_analyzer import RealTimeSpectrumAnalyzer
from fft_worker import FFTWorkerThread
from time_space_plot import TimeSpacePlotWidget
from logger import get_logger

log = get_logger("gui")


class MainWindow(QMainWindow):
    """Main application window for WFBG-7825."""

    def __init__(self, simulation_mode: bool = False):
        super().__init__()
        log.info(f"MainWindow initializing (simulation_mode={simulation_mode})")
        self.simulation_mode = simulation_mode

        self.api: Optional[WFBG7825API] = None
        self.acq_thread: Optional[AcquisitionThread] = None
        self.data_saver: Optional[FrameBasedFileSaver] = None
        self.spectrum_analyzer = RealTimeSpectrumAnalyzer()
        self.fft_worker = FFTWorkerThread(self)  # 新增FFT工作线程

        self.params = AllParams()

        # Peak detection state
        self._fbg_num_per_ch = 0
        self._peak_detection_done = False
        self._ch0_peak_info = None
        self._ch1_peak_info = None

        # Display data buffers
        self._current_monitor_data = None

        # Performance tracking
        self._last_data_time = 0
        self._data_count = 0
        self._gui_update_count = 0
        self._raw_data_count = 0
        self._last_raw_display_time = 0

        # Raw data optimization tracking
        self._last_time_domain_update = 0
        self._last_fft_update = 0
        self._raw_frame_buffer = []  # 存储用于平均的帧

        # System monitoring
        self._last_system_update = 0
        self._cpu_percent = 0.0
        self._disk_free_gb = 0.0

        # Setup UI
        self.setWindowTitle("eDAS-fs-7825 gh.26.2.15")
        self.setMinimumSize(1400, 950)

        self._setup_ui()
        self._setup_plots()
        self._setup_time_space_widget()
        self._connect_signals()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(MONITOR_UPDATE_INTERVALS['buffer_status_ms'])

        self._system_timer = QTimer(self)
        self._system_timer.timeout.connect(self._update_system_status)
        self._system_timer.start(MONITOR_UPDATE_INTERVALS['system_status_s'] * 1000)

        self._update_file_estimates()

        if not simulation_mode:
            self._init_device()
        else:
            self._update_device_status(True)

        log.info("MainWindow initialized")

    # ----- UI LAYOUT -----

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_vertical_layout = QVBoxLayout(central_widget)
        main_vertical_layout.setContentsMargins(10, 10, 10, 10)

        # Header
        header_widget = self._create_header()
        main_vertical_layout.addWidget(header_widget)

        # Content
        left_panel = self._create_parameter_panel()
        left_panel.setMaximumWidth(380)
        left_panel.setMinimumWidth(340)

        right_panel = self._create_plot_panel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([360, 1040])

        main_vertical_layout.addWidget(splitter)

        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self._device_status_label = QLabel("Device: Disconnected")
        self._data_rate_label = QLabel("Data Rate: 0 MB/s")
        self._fiber_length_label = QLabel("Fiber: 0 m")
        self.statusBar.addWidget(self._device_status_label)
        self.statusBar.addWidget(self._data_rate_label)
        self.statusBar.addWidget(self._fiber_length_label)

    def _create_header(self) -> QWidget:
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        header.setFixedHeight(50)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 3, 10, 3)

        logo_label = QLabel()
        project_root = os.path.dirname(os.path.dirname(__file__))
        logo_path = os.path.join(project_root, "resources", "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            scaled_pixmap = pixmap.scaledToHeight(40, Qt.SmoothTransformation)
            logo_label.setPixmap(scaled_pixmap)
        else:
            logo_label.setText("[LOGO]")
        layout.addWidget(logo_label)

        title_label = QLabel("\u5206\u5e03\u5f0f\u5149\u7ea4\u58f0\u7eb9\u4f20\u611f\u7cfb\u7edf\uff08eDAS\uff09")
        title_font = QFont("SimHei", 28, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label, 1)
        layout.addStretch()

        return header

    def _create_parameter_panel(self) -> QWidget:
        # Use scroll area to handle small screens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)
        layout.setContentsMargins(5, 5, 5, 5)

        INPUT_MIN_HEIGHT = 22
        INPUT_MAX_WIDTH = 80

        panel.setStyleSheet("""
            QGroupBox {
                font-family: 'SimHei', 'Microsoft YaHei';
                font-size: 12px;
                font-weight: bold;
            }
            QLabel {
                font-family: 'Times New Roman', 'SimHei';
                font-size: 11px;
            }
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
                font-family: 'Times New Roman';
                font-size: 11px;
                max-height: 22px;
            }
            QComboBox {
                max-width: 100px;
            }
            QRadioButton, QCheckBox {
                font-family: 'Times New Roman', 'SimHei';
                font-size: 10px;
            }
            QPushButton {
                font-family: 'Times New Roman', 'SimHei';
                font-size: 12px;
            }
        """)

        # ===== Basic Parameters =====
        basic_group = QGroupBox("Basic Parameters")
        basic_layout = QGridLayout(basic_group)
        basic_layout.setSpacing(4)
        basic_layout.setContentsMargins(8, 12, 8, 8)

        # Row 0: Clock | Trigger
        basic_layout.addWidget(QLabel("Clock:"), 0, 0)
        self.clk_internal_radio = QRadioButton("Int")
        self.clk_external_radio = QRadioButton("Ext")
        self.clk_internal_radio.setChecked(True)
        clk_group = QButtonGroup(self)
        clk_group.addButton(self.clk_internal_radio, 0)
        clk_group.addButton(self.clk_external_radio, 1)
        clk_layout = QHBoxLayout()
        clk_layout.setSpacing(2)
        clk_layout.addWidget(self.clk_internal_radio)
        clk_layout.addWidget(self.clk_external_radio)
        basic_layout.addLayout(clk_layout, 0, 1)

        basic_layout.addWidget(QLabel("Trig:"), 0, 2)
        self.trig_in_radio = QRadioButton("In")
        self.trig_out_radio = QRadioButton("Out")
        self.trig_out_radio.setChecked(True)
        trig_group = QButtonGroup(self)
        trig_group.addButton(self.trig_in_radio, 0)
        trig_group.addButton(self.trig_out_radio, 1)
        trig_layout = QHBoxLayout()
        trig_layout.setSpacing(2)
        trig_layout.addWidget(self.trig_in_radio)
        trig_layout.addWidget(self.trig_out_radio)
        basic_layout.addLayout(trig_layout, 0, 3)

        # Row 1: Scan Rate | Pulse Width
        basic_layout.addWidget(QLabel("Scan(Hz):"), 1, 0)
        self.scan_rate_spin = QSpinBox()
        self.scan_rate_spin.setRange(1, 100000)
        self.scan_rate_spin.setValue(2000)
        self.scan_rate_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.scan_rate_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        basic_layout.addWidget(self.scan_rate_spin, 1, 1)

        basic_layout.addWidget(QLabel("Pulse(ns):"), 1, 2)
        self.pulse_width_spin = QSpinBox()
        self.pulse_width_spin.setRange(4, 1000)
        self.pulse_width_spin.setValue(100)
        self.pulse_width_spin.setSingleStep(4)
        self.pulse_width_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.pulse_width_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        basic_layout.addWidget(self.pulse_width_spin, 1, 3)

        # Row 2: Points | Bypass
        basic_layout.addWidget(QLabel("Points:"), 2, 0)
        self.point_num_spin = QSpinBox()
        self.point_num_spin.setRange(512, 262144)
        self.point_num_spin.setValue(20480)
        self.point_num_spin.setSingleStep(512)
        self.point_num_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.point_num_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        basic_layout.addWidget(self.point_num_spin, 2, 1)

        basic_layout.addWidget(QLabel("Bypass:"), 2, 2)
        self.bypass_spin = QSpinBox()
        self.bypass_spin.setRange(0, 65535)
        self.bypass_spin.setValue(60)
        self.bypass_spin.setSingleStep(4)
        self.bypass_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.bypass_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        basic_layout.addWidget(self.bypass_spin, 2, 3)

        # Row 3: Center Freq (aligned with Points input above)
        basic_layout.addWidget(QLabel("CenterFreq:"), 3, 0)
        self.center_freq_combo = QComboBox()
        for label, value in CENTER_FREQ_OPTIONS:
            self.center_freq_combo.addItem(label, value)
        self.center_freq_combo.setCurrentIndex(1)  # Default 200MHz
        self.center_freq_combo.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.center_freq_combo.setMaximumWidth(INPUT_MAX_WIDTH)  # Same width as Points input
        basic_layout.addWidget(self.center_freq_combo, 3, 1)

        layout.addWidget(basic_group)

        # ===== Upload Parameters =====
        upload_group = QGroupBox("Upload Parameters")
        upload_layout = QGridLayout(upload_group)
        upload_layout.setSpacing(4)
        upload_layout.setContentsMargins(8, 12, 8, 8)

        upload_layout.addWidget(QLabel("Source:"), 0, 0)
        self.data_source_combo = QComboBox()
        for label, value in DATA_SOURCE_OPTIONS:
            self.data_source_combo.addItem(label, value)
        self.data_source_combo.setCurrentIndex(2)  # Default Phase
        self.data_source_combo.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.data_source_combo.setMaximumWidth(INPUT_MAX_WIDTH)  # Align with other inputs
        upload_layout.addWidget(self.data_source_combo, 0, 1)

        upload_layout.addWidget(QLabel("Channels:"), 0, 2)
        self.channel_combo = QComboBox()
        for label, value in CHANNEL_NUM_OPTIONS:
            self.channel_combo.addItem(label, value)
        self.channel_combo.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.channel_combo.setMaximumWidth(INPUT_MAX_WIDTH)  # Align with other inputs
        upload_layout.addWidget(self.channel_combo, 0, 3)

        layout.addWidget(upload_group)

        # ===== Phase Demod Parameters (simplified for 7825) =====
        phase_group = QGroupBox("Phase Demod Parameters")
        phase_layout = QGridLayout(phase_group)
        phase_layout.setSpacing(4)
        phase_layout.setContentsMargins(8, 12, 8, 8)

        self.polar_div_check = QCheckBox("Polarization Diversity")
        phase_layout.addWidget(self.polar_div_check, 0, 0, 1, 2)

        phase_layout.addWidget(QLabel("Detrend(Hz):"), 0, 2)
        self.detrend_bw_spin = QDoubleSpinBox()
        self.detrend_bw_spin.setRange(0.0, 10000.0)
        self.detrend_bw_spin.setValue(0.5)
        self.detrend_bw_spin.setSingleStep(0.1)
        self.detrend_bw_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.detrend_bw_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        phase_layout.addWidget(self.detrend_bw_spin, 0, 3)

        layout.addWidget(phase_group)

        # ===== Peak Detection (NEW for 7825) =====
        peak_group = QGroupBox("Peak Detection")
        peak_layout = QGridLayout(peak_group)
        peak_layout.setSpacing(4)
        peak_layout.setContentsMargins(8, 12, 8, 8)
        # Set smaller horizontal spacing between peak status labels
        peak_layout.setHorizontalSpacing(2)

        peak_layout.addWidget(QLabel("AmpBase:"), 0, 0)
        self.amp_base_spin = QSpinBox()
        self.amp_base_spin.setRange(0, 65535)
        self.amp_base_spin.setValue(2000)
        self.amp_base_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.amp_base_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        peak_layout.addWidget(self.amp_base_spin, 0, 1)

        peak_layout.addWidget(QLabel("FBG Interval(m):"), 0, 2)
        self.fbg_interval_spin = QDoubleSpinBox()
        self.fbg_interval_spin.setRange(0.1, 100.0)
        self.fbg_interval_spin.setValue(5.0)
        self.fbg_interval_spin.setSingleStep(0.5)
        self.fbg_interval_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.fbg_interval_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        peak_layout.addWidget(self.fbg_interval_spin, 0, 3)

        # Get Peak Info button (reduced height, same width)
        self.get_peak_btn = QPushButton("Get Peak Info")
        self.get_peak_btn.setMinimumHeight(22)  # Reduced from 28 to 22
        self.get_peak_btn.setMaximumHeight(22)
        self.get_peak_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:pressed { background-color: #1565C0; }
        """)
        peak_layout.addWidget(self.get_peak_btn, 1, 0, 1, 2)

        self.save_peak_check = QCheckBox("Save Peak Info")
        peak_layout.addWidget(self.save_peak_check, 1, 2, 1, 2)

        # Peak count labels (improved compact layout)
        # Create a horizontal layout for compact peak status display
        peak_status_layout = QHBoxLayout()
        peak_status_layout.setSpacing(8)  # Reduced spacing between groups

        # CH0 Peaks group
        ch0_label = QLabel("CH0 Peaks:")
        ch0_label.setContentsMargins(0, 0, 2, 0)  # Minimal margin
        self.ch0_peak_label = QLabel("0")
        self.ch0_peak_label.setStyleSheet("font-weight: bold; color: #1f77b4;")
        self.ch0_peak_label.setContentsMargins(0, 0, 0, 0)

        # CH1 Peaks group
        ch1_label = QLabel("CH1 Peaks:")
        ch1_label.setContentsMargins(0, 0, 2, 0)  # Minimal margin
        self.ch1_peak_label = QLabel("0")
        self.ch1_peak_label.setStyleSheet("font-weight: bold; color: #ff7f0e;")
        self.ch1_peak_label.setContentsMargins(0, 0, 0, 0)

        # Valid FBG group
        valid_label = QLabel("Valid FBG:")
        valid_label.setContentsMargins(0, 0, 2, 0)  # Minimal margin
        self.valid_fbg_label = QLabel("0")
        self.valid_fbg_label.setStyleSheet("font-weight: bold; color: #2ca02c;")
        self.valid_fbg_label.setContentsMargins(0, 0, 0, 0)

        # Add to horizontal layout
        peak_status_layout.addWidget(ch0_label)
        peak_status_layout.addWidget(self.ch0_peak_label)
        peak_status_layout.addSpacing(10)  # Small gap between groups
        peak_status_layout.addWidget(ch1_label)
        peak_status_layout.addWidget(self.ch1_peak_label)
        peak_status_layout.addSpacing(10)  # Small gap between groups
        peak_status_layout.addWidget(valid_label)
        peak_status_layout.addWidget(self.valid_fbg_label)
        peak_status_layout.addStretch()  # Push everything to the left

        # Add the horizontal layout to the grid
        peak_layout.addLayout(peak_status_layout, 2, 0, 1, 6)  # Span across all columns

        layout.addWidget(peak_group)

        # ===== Display Control =====
        display_group = QGroupBox("Display Control")
        display_layout = QGridLayout(display_group)
        display_layout.setSpacing(4)
        display_layout.setContentsMargins(8, 12, 8, 8)

        display_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.mode_time_radio = QRadioButton("Time")
        self.mode_space_radio = QRadioButton("Space")
        self.mode_time_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.mode_time_radio, 0)
        mode_group.addButton(self.mode_space_radio, 1)
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(2)
        mode_layout.addWidget(self.mode_time_radio)
        mode_layout.addWidget(self.mode_space_radio)
        display_layout.addLayout(mode_layout, 0, 1)

        display_layout.addWidget(QLabel("FBG Idx:"), 0, 2)
        self.region_index_spin = QSpinBox()
        self.region_index_spin.setRange(0, 65535)
        self.region_index_spin.setValue(0)
        self.region_index_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.region_index_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        display_layout.addWidget(self.region_index_spin, 0, 3)

        display_layout.addWidget(QLabel("Frames:"), 1, 0)
        self.frame_num_spin = QSpinBox()
        self.frame_num_spin.setRange(1, 10000)
        self.frame_num_spin.setValue(1024)
        self.frame_num_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.frame_num_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        display_layout.addWidget(self.frame_num_spin, 1, 1)

        self.spectrum_enable_check = QCheckBox("Spectrum")
        self.spectrum_enable_check.setChecked(True)
        display_layout.addWidget(self.spectrum_enable_check, 1, 2)

        self.psd_check = QCheckBox("PSD")
        display_layout.addWidget(self.psd_check, 1, 3)

        # Add rad checkbox on second row
        self.rad_check = QCheckBox("rad")
        self.rad_check.setChecked(self.params.display.rad_enable)
        self.rad_check.setToolTip("Convert phase data to radians for display (/ 32767 * π)")
        display_layout.addWidget(self.rad_check, 2, 0)

        layout.addWidget(display_group)

        # ===== Data Save =====
        save_group = QGroupBox("Data Save")
        save_layout = QGridLayout(save_group)
        save_layout.setSpacing(4)
        save_layout.setContentsMargins(8, 12, 8, 8)

        self.save_enable_check = QCheckBox("Enable")
        save_layout.addWidget(self.save_enable_check, 0, 0)

        save_layout.addWidget(QLabel("Path:"), 0, 1)
        path_layout = QHBoxLayout()
        path_layout.setSpacing(2)
        self.save_path_edit = QLineEdit(self.params.save.path)
        self.save_path_edit.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.browse_btn = QPushButton("...")
        self.browse_btn.setMaximumWidth(25)
        self.browse_btn.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.browse_btn.clicked.connect(self._browse_save_path)
        path_layout.addWidget(self.save_path_edit)
        path_layout.addWidget(self.browse_btn)
        save_layout.addLayout(path_layout, 0, 2, 1, 2)

        save_layout.addWidget(QLabel("Frames/File:"), 1, 0)
        self.frames_per_file_spin = QSpinBox()
        self.frames_per_file_spin.setRange(1, 100)
        self.frames_per_file_spin.setValue(self.params.save.frames_per_file)
        self.frames_per_file_spin.setMinimumHeight(INPUT_MIN_HEIGHT)
        self.frames_per_file_spin.setMaximumWidth(INPUT_MAX_WIDTH)
        self.frames_per_file_spin.valueChanged.connect(self._update_file_estimates)
        save_layout.addWidget(self.frames_per_file_spin, 1, 1)

        save_layout.addWidget(QLabel("Est. Size:"), 1, 2)
        self.file_size_label = QLabel("~?MB/file")
        self.file_size_label.setStyleSheet("font-weight: normal; color: #666666;")
        save_layout.addWidget(self.file_size_label, 1, 3)

        layout.addWidget(save_group)

        # ===== Control Buttons =====
        control_layout = QHBoxLayout()

        self.start_btn = QPushButton("START")
        self.start_btn.setMinimumHeight(28)  # Reduced from 38 to 28
        self.start_btn.setMaximumHeight(28)
        # self.start_btn.setMaximumWidth(80)   # Set maximum width
        self._set_start_btn_ready()

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setMinimumHeight(28)   # Reduced from 38 to 28
        self.stop_btn.setMaximumHeight(28)
        # self.stop_btn.setMaximumWidth(80)    # Set maximum width
        self._set_stop_btn_disabled()

        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        layout.addLayout(control_layout)

        layout.addStretch()

        scroll.setWidget(panel)
        return scroll

    def _set_start_btn_ready(self):
        self.start_btn.setEnabled(True)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white; font-weight: bold;
                font-size: 14px; border: none; border-radius: 5px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:pressed { background-color: #3d8b40; }
        """)

    def _set_start_btn_running(self):
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #9E9E9E; color: #666666; font-weight: bold;
                font-size: 14px; border: none; border-radius: 5px;
            }
        """)

    def _set_stop_btn_disabled(self):
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #BDBDBD; color: #757575; font-weight: bold;
                font-size: 14px; border: none; border-radius: 5px;
            }
        """)

    def _set_stop_btn_enabled(self):
        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white; font-weight: bold;
                font-size: 14px; border: none; border-radius: 5px;
            }
            QPushButton:hover { background-color: #da190b; }
            QPushButton:pressed { background-color: #c41508; }
        """)

    def _create_plot_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)

        # Configure pyqtgraph
        pg.setConfigOptions(antialias=True)

        # Create tab widget
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setTabPosition(QTabWidget.North)

        # Set tab titles font style
        self.plot_tabs.setStyleSheet("""
            QTabWidget::tab-bar {
                alignment: left;
            }
            QTabBar::tab {
                font-family: 'Arial';
                font-size: 12px;
                font-weight: normal;
                padding: 6px 15px;
                margin: 1px;
                min-width: 90px;
            }
            QTabBar::tab:selected {
                font-weight: bold;
            }
        """)

        # Tab 1: Traditional plots (Time/Space + FFT + Monitor)
        self._create_traditional_plots_tab()

        # Tab 2: Time-Space plot
        self._create_time_space_tab()

        layout.addWidget(self.plot_tabs)

        # System monitoring bar
        monitor_frame = QFrame()
        monitor_frame.setFrameStyle(QFrame.StyledPanel)
        monitor_frame.setMaximumHeight(40)
        monitor_layout = QHBoxLayout(monitor_frame)
        monitor_layout.setSpacing(15)

        monitor_layout.addWidget(QLabel("Status:"))

        self.hw_buffer_label = QLabel("HW: 0/50")
        self.hw_buffer_bar = QProgressBar()
        self.hw_buffer_bar.setMaximumWidth(80)
        self.hw_buffer_bar.setMaximumHeight(16)
        monitor_layout.addWidget(self.hw_buffer_label)
        monitor_layout.addWidget(self.hw_buffer_bar)

        self.storage_queue_label = QLabel("STO: 0/200")
        self.storage_queue_bar = QProgressBar()
        self.storage_queue_bar.setMaximumWidth(80)
        self.storage_queue_bar.setMaximumHeight(16)
        monitor_layout.addWidget(self.storage_queue_label)
        monitor_layout.addWidget(self.storage_queue_bar)

        separator = QLabel("|")
        separator.setStyleSheet("color: gray;")
        monitor_layout.addWidget(separator)

        self.cpu_label = QLabel("CPU: 0%")
        self.disk_label = QLabel("Disk: 0GB free")
        self.polling_label = QLabel("Poll: 1ms")
        monitor_layout.addWidget(self.cpu_label)
        monitor_layout.addWidget(self.disk_label)
        monitor_layout.addWidget(self.polling_label)

        separator2 = QLabel("|")
        separator2.setStyleSheet("color: gray;")
        monitor_layout.addWidget(separator2)

        self.buffer_label = QLabel("Buffer: 0 MB")
        self.frames_label = QLabel("Frames: 0")
        self.save_status_label = QLabel("Save: Off")
        monitor_layout.addWidget(self.buffer_label)
        monitor_layout.addWidget(self.frames_label)
        monitor_layout.addWidget(self.save_status_label)

        monitor_layout.addStretch()

        layout.addWidget(monitor_frame)

        return panel

    def _create_traditional_plots_tab(self):
        """Create the traditional plots tab with existing functionality"""
        tab1_widget = QWidget()
        tab1_layout = QVBoxLayout(tab1_widget)
        tab1_layout.setSpacing(10)
        tab1_layout.setContentsMargins(5, 5, 5, 10)

        # Create plots with improved styling
        self.plot_widget_1 = pg.PlotWidget()
        self.plot_widget_2 = pg.PlotWidget()
        self.plot_widget_3 = pg.PlotWidget()

        # Configure plot styles
        plot_titles = ["Time Domain Data", "FFT Spectrum", "Monitor (FBG Amplitude)"]
        self.plot_widgets = [self.plot_widget_1, self.plot_widget_2, self.plot_widget_3]

        for i, pw in enumerate(self.plot_widgets):
            pw.setBackground('w')

            # Set custom title with Times New Roman font and dark blue color
            blue_title = f'<span style="color: rgb(0,0,139); font-family: Times New Roman; font-size: 9pt">{plot_titles[i]}</span>'
            pw.setLabel('top', blue_title)

            # Configure axes
            x_axis = pw.getAxis('bottom')
            y_axis = pw.getAxis('left')
            top_axis = pw.getAxis('top')

            # Show top axis for title but hide its ticks
            pw.showAxis('top', show=True)
            pw.showAxis('right', show=False)
            top_axis.setStyle(showValues=False, tickLength=0)

            # Grid and tick configuration
            pw.showGrid(x=True, y=True, alpha=0.6)

            # Set fonts - using 8pt as per example project
            tick_font = QFont("Times New Roman", 8)

            # Configure tick style
            x_axis.setStyle(showValues=True, tickLength=4, tickTextOffset=6)
            y_axis.setStyle(showValues=True, tickLength=4, tickTextOffset=4)

            # Set tick fonts
            x_axis.setTickFont(tick_font)
            y_axis.setTickFont(tick_font)

            # Set axis colors
            x_axis.setPen('k')
            y_axis.setPen('k')
            x_axis.setTextPen('k')
            y_axis.setTextPen('k')

        # Set specific labels for each plot
        self.plot_widget_1.setLabel('bottom', 'Sample Index',
                                   color='k', **{'font-family': 'Times New Roman', 'font-size': '8pt'})
        self.plot_widget_1.setLabel('left', 'Amp.',
                                   color='k', **{'font-family': 'Times New Roman', 'font-size': '8pt'})

        self.plot_widget_2.setLabel('bottom', 'Frequency (Hz)',
                                   color='k', **{'font-family': 'Times New Roman', 'font-size': '8pt'})
        self.plot_widget_2.setLabel('left', 'Amp. (dB)',
                                   color='k', **{'font-family': 'Times New Roman', 'font-size': '8pt'})

        self.plot_widget_3.setLabel('bottom', 'FBG Index',
                                   color='k', **{'font-family': 'Times New Roman', 'font-size': '8pt'})
        self.plot_widget_3.setLabel('left', 'Amp.',
                                   color='k', **{'font-family': 'Times New Roman', 'font-size': '8pt'})

        # Initialize plot curves
        self.plot_curve_1 = []
        self.spectrum_curve = self.plot_widget_2.plot(pen=pg.mkPen('#9467bd', width=1.5))
        self.plot_widget_2.setLogMode(x=False, y=False)
        self.monitor_curves = []

        # Set plot widget sizes
        for pw, min_h, max_h in [(self.plot_widget_1, 180, 210),
                                  (self.plot_widget_2, 180, 210),
                                  (self.plot_widget_3, 130, 160)]:
            pw.setMinimumHeight(min_h)
            pw.setMaximumHeight(max_h)
            pw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Add widgets to layout
        tab1_layout.addWidget(self.plot_widget_1)
        tab1_layout.addWidget(self.plot_widget_2)
        tab1_layout.addWidget(self.plot_widget_3)

        # Add tab to tab widget
        self.plot_tabs.addTab(tab1_widget, "Traditional Plots")

    def _create_time_space_tab(self):
        """Create the time-space tab with TimeSpacePlotWidget"""
        tab2_widget = QWidget()
        tab2_layout = QVBoxLayout(tab2_widget)
        tab2_layout.setSpacing(5)
        tab2_layout.setContentsMargins(5, 5, 5, 5)

        # Create TimeSpacePlotWidget
        self.time_space_widget = TimeSpacePlotWidget()
        tab2_layout.addWidget(self.time_space_widget)

        # Add tab to tab widget
        self.plot_tabs.addTab(tab2_widget, "Time-Space Plot")

    def _setup_plots(self):
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']

        for i in range(4):
            curve = self.plot_widget_1.plot(pen=pg.mkPen(colors[i], width=1.5))
            self.plot_curve_1.append(curve)

        for i in range(2):
            curve = self.plot_widget_3.plot(pen=pg.mkPen(colors[i], width=1.5))
            self.monitor_curves.append(curve)

    def _setup_time_space_widget(self):
        """Initialize time-space widget with default parameters"""
        if hasattr(self, 'time_space_widget') and self.time_space_widget:
            # Set parameters from config
            ts_params = {
                'window_frames': self.params.time_space.window_frames,
                'distance_range_start': self.params.time_space.distance_range_start,
                'distance_range_end': self.params.time_space.distance_range_end,
                'time_downsample': self.params.time_space.time_downsample,
                'space_downsample': self.params.time_space.space_downsample,
                'colormap_type': self.params.time_space.colormap_type,
                'vmin': self.params.time_space.vmin,
                'vmax': self.params.time_space.vmax
            }
            self.time_space_widget.set_parameters(ts_params)

    # ----- SIGNAL CONNECTIONS -----

    def _connect_signals(self):
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.get_peak_btn.clicked.connect(self._on_get_peak_info)

        self.data_source_combo.currentIndexChanged.connect(self._on_data_source_changed)
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        self.point_num_spin.valueChanged.connect(self._update_calculated_values)
        self.scan_rate_spin.valueChanged.connect(self._update_calculated_values)
        self.frames_per_file_spin.valueChanged.connect(self._update_file_estimates)

    # ----- DEVICE INIT -----

    def _init_device(self):
        log.info("Initializing device...")
        try:
            self.api = WFBG7825API()
            result = self.api.open()
            if result == 0:
                self._update_device_status(True)
                log.info("Device initialized successfully")
            else:
                self._update_device_status(False)
                log.error(f"Failed to open device: error code {result}")
                QMessageBox.warning(self, "Warning", f"Failed to open device: error code {result}")
        except FileNotFoundError as e:
            self._update_device_status(False)
            log.error(f"DLL not found: {e}")
            QMessageBox.warning(self, "Warning", f"DLL not found: {e}")
        except Exception as e:
            self._update_device_status(False)
            log.exception(f"Failed to initialize device: {e}")
            QMessageBox.warning(self, "Warning", f"Failed to initialize device: {e}")

    def _update_device_status(self, connected: bool):
        if connected:
            self._device_status_label.setText("Device: Connected")
            self._device_status_label.setStyleSheet("color: green;")
        else:
            self._device_status_label.setText("Device: Disconnected")
            self._device_status_label.setStyleSheet("color: red;")

    # ----- PARAMETER COLLECTION -----

    def _collect_params(self) -> AllParams:
        params = AllParams()

        params.basic.clk_src = ClockSource.EXTERNAL if self.clk_external_radio.isChecked() else ClockSource.INTERNAL
        params.basic.trig_dir = TriggerDirection.INPUT if self.trig_in_radio.isChecked() else TriggerDirection.OUTPUT
        params.basic.scan_rate = self.scan_rate_spin.value()
        params.basic.pulse_width_ns = self.pulse_width_spin.value()
        params.basic.point_num_per_scan = self.point_num_spin.value()
        params.basic.bypass_point_num = self.bypass_spin.value()
        params.basic.center_freq_mhz = self.center_freq_combo.currentData()

        params.upload.channel_num = self.channel_combo.currentData()
        params.upload.data_source = self.data_source_combo.currentData()

        params.phase_demod.polarization_diversity = self.polar_div_check.isChecked()
        params.phase_demod.detrend_bw = self.detrend_bw_spin.value()

        params.peak_detection.amp_base_line = self.amp_base_spin.value()
        params.peak_detection.fbg_interval_m = self.fbg_interval_spin.value()

        params.display.mode = DisplayMode.SPACE if self.mode_space_radio.isChecked() else DisplayMode.TIME
        params.display.region_index = self.region_index_spin.value()
        params.display.frame_num = self.frame_num_spin.value()
        params.display.spectrum_enable = self.spectrum_enable_check.isChecked()
        params.display.psd_enable = self.psd_check.isChecked()
        params.display.rad_enable = self.rad_check.isChecked()

        # Collect time-space parameters if widget exists
        if hasattr(self, 'time_space_widget') and self.time_space_widget:
            ts_params = self.time_space_widget.get_parameters()
            params.time_space.window_frames = ts_params.get('window_frames', 5)
            params.time_space.distance_range_start = ts_params.get('distance_range_start', 40)
            params.time_space.distance_range_end = ts_params.get('distance_range_end', 100)
            params.time_space.time_downsample = ts_params.get('time_downsample', 50)
            params.time_space.space_downsample = ts_params.get('space_downsample', 2)
            params.time_space.colormap_type = ts_params.get('colormap_type', "jet")
            params.time_space.vmin = ts_params.get('vmin', -0.02)
            params.time_space.vmax = ts_params.get('vmax', 0.02)

        params.save.enable = self.save_enable_check.isChecked()
        params.save.path = self.save_path_edit.text()
        params.save.frames_per_file = self.frames_per_file_spin.value()

        return params

    def _validate_params(self, params: AllParams) -> tuple:
        valid, msg = validate_point_num(
            params.basic.point_num_per_scan,
            params.upload.channel_num
        )
        if not valid:
            return False, msg

        # Polarization diversity + phase requires ch_num=1
        if (params.phase_demod.polarization_diversity and
            params.upload.data_source == DataSource.PHASE and
            params.upload.channel_num != 1):
            return False, "Polarization diversity with phase data requires channel_num = 1"

        return True, ""

    def _configure_device(self, params: AllParams) -> bool:
        if self.api is None:
            return False

        log.info("Configuring device...")
        try:
            self.api.set_clk_src(params.basic.clk_src)
            self.api.set_trig_param(
                params.basic.trig_dir,
                params.basic.scan_rate,
                params.basic.pulse_width_ns
            )
            self.api.set_origin_point_num_per_scan(params.basic.point_num_per_scan)
            self.api.set_bypass_point_num(params.basic.bypass_point_num)
            self.api.set_upload_data_param(
                params.upload.channel_num,
                params.upload.data_source
            )
            self.api.set_center_freq(params.basic.center_freq_mhz * 1000000)
            self.api.set_phase_dem_param(
                params.phase_demod.polarization_diversity,
                params.phase_demod.detrend_bw
            )

            log.info("Device configured successfully")
            return True

        except WFBG7825Error as e:
            log.error(f"Failed to configure device: {e}")
            QMessageBox.critical(self, "Error", f"Failed to configure device: {e}")
            return False

    # ----- PEAK DETECTION -----

    @pyqtSlot()
    def _on_get_peak_info(self):
        """Handle Get Peak Info button click."""
        log.info("=== Get Peak Info clicked ===")

        params = self._collect_params()
        valid, msg = self._validate_params(params)
        if not valid:
            QMessageBox.warning(self, "Invalid Parameters", msg)
            return

        self.params = params

        if not self.simulation_mode:
            if not self._configure_device(params):
                return

            try:
                (ch0_cnt, ch0_info, ch0_amp,
                 ch1_cnt, ch1_info, ch1_amp) = self.api.get_peak_info(
                    params.peak_detection.amp_base_line,
                    params.peak_detection.fbg_interval_m,
                    params.basic.point_num_per_scan
                )

                self._ch0_peak_info = ch0_info
                self._ch1_peak_info = ch1_info

                fbg_num = self.api.get_valid_fbg_num()
                self._fbg_num_per_ch = fbg_num
                self._peak_detection_done = True

                # Update labels
                self.ch0_peak_label.setText(str(ch0_cnt))
                self.ch1_peak_label.setText(str(ch1_cnt))
                self.valid_fbg_label.setText(str(fbg_num))

                # Display amplitude and peak markers
                self._display_peak_info(ch0_info, ch0_amp, ch1_info, ch1_amp,
                                       params.upload.channel_num,
                                       params.basic.point_num_per_scan)

                # Save peak info if requested
                if self.save_peak_check.isChecked():
                    self._save_peak_info_file(ch0_info, ch0_amp, ch1_info, ch1_amp)

                log.info(f"Peak detection done: ch0={ch0_cnt}, ch1={ch1_cnt}, valid_fbg={fbg_num}")

            except WFBG7825Error as e:
                log.error(f"Peak detection failed: {e}")
                QMessageBox.critical(self, "Error", f"Peak detection failed: {e}")
        else:
            # Simulation mode
            point_num = params.basic.point_num_per_scan
            ch0_cnt = max(1, point_num // 50)
            ch1_cnt = max(1, point_num // 50)
            fbg_num = max(ch0_cnt, ch1_cnt)

            self._fbg_num_per_ch = fbg_num
            self._peak_detection_done = True

            self.ch0_peak_label.setText(str(ch0_cnt))
            self.ch1_peak_label.setText(str(ch1_cnt))
            self.valid_fbg_label.setText(str(fbg_num))

            # Generate simulated peak display
            ch0_amp = np.random.randint(1000, 10000, point_num, dtype=np.uint16)
            ch0_info = np.zeros(point_num, dtype=np.uint32)
            peak_positions = np.linspace(10, point_num - 10, ch0_cnt, dtype=int)
            ch0_info[peak_positions] = 1

            ch1_amp = np.random.randint(1000, 10000, point_num, dtype=np.uint16)
            ch1_info = np.zeros(point_num, dtype=np.uint32)
            ch1_info[peak_positions] = 1

            self._display_peak_info(ch0_info, ch0_amp, ch1_info, ch1_amp,
                                   params.upload.channel_num, point_num)

            log.info(f"Simulated peak detection: fbg_num={fbg_num}")

    def _display_peak_info(self, ch0_info, ch0_amp, ch1_info, ch1_amp,
                          channel_num, point_num):
        """Display amplitude waveform and peak markers."""
        # Clear plots
        for curve in self.plot_curve_1:
            curve.setData([])
        self.spectrum_curve.setData([])

        # Plot 1: CH0 amplitude + peak markers
        self.plot_curve_1[0].setData(ch0_amp[:point_num].astype(np.float32))

        # Scale peak info for visibility
        peak_markers = ch0_info[:point_num].astype(np.float32) * 10000
        self.plot_curve_1[1].setData(peak_markers)

        if channel_num == 2:
            # Plot 2: CH1 amplitude + peak markers
            self.plot_curve_1[2].setData(ch1_amp[:point_num].astype(np.float32))
            peak_markers_1 = ch1_info[:point_num].astype(np.float32) * 10000
            self.plot_curve_1[3].setData(peak_markers_1)

    def _save_peak_info_file(self, ch0_info, ch0_amp, ch1_info, ch1_amp):
        """Save peak info to binary file."""
        from datetime import datetime
        save_dir = self.save_path_edit.text()
        os.makedirs(save_dir, exist_ok=True)
        now = datetime.now()
        filename = f"peak_info-{now.strftime('%H-%M-%S')}.bin"
        filepath = os.path.join(save_dir, filename)

        with open(filepath, 'wb') as f:
            f.write(ch0_info.tobytes())
            f.write(ch0_amp.tobytes())
            f.write(ch1_info.tobytes())
            f.write(ch1_amp.tobytes())

        log.info(f"Peak info saved to {filepath}")

    # ----- ACQUISITION CONTROL -----

    @pyqtSlot()
    def _on_start(self):
        log.info("=== START button clicked ===")

        params = self._collect_params()
        valid, msg = self._validate_params(params)
        if not valid:
            QMessageBox.warning(self, "Invalid Parameters", msg)
            return

        self.params = params

        # Configure device
        if not self.simulation_mode:
            if not self._configure_device(params):
                return

            # Must run peak detection before start
            if not self._peak_detection_done:
                log.info("Running peak detection (required before start)...")
                try:
                    (ch0_cnt, ch0_info, ch0_amp,
                     ch1_cnt, ch1_info, ch1_amp) = self.api.get_peak_info(
                        params.peak_detection.amp_base_line,
                        params.peak_detection.fbg_interval_m,
                        params.basic.point_num_per_scan
                    )
                    self._ch0_peak_info = ch0_info
                    self._ch1_peak_info = ch1_info
                    self.ch0_peak_label.setText(str(ch0_cnt))
                    self.ch1_peak_label.setText(str(ch1_cnt))
                except WFBG7825Error as e:
                    QMessageBox.critical(self, "Error", f"Peak detection failed: {e}")
                    return

            # Get valid FBG num
            try:
                fbg_num = self.api.get_valid_fbg_num()
                self._fbg_num_per_ch = fbg_num
                self.valid_fbg_label.setText(str(fbg_num))
            except WFBG7825Error as e:
                QMessageBox.critical(self, "Error", f"Failed to get FBG num: {e}")
                return

            # Allocate buffers
            self.api.allocate_buffers(
                params.basic.point_num_per_scan,
                params.upload.channel_num,
                params.display.frame_num,
                self._fbg_num_per_ch
            )

            # Start device
            try:
                self.api.start()
            except WFBG7825Error as e:
                QMessageBox.critical(self, "Error", f"Failed to start: {e}")
                return
        else:
            # Simulation: ensure fbg_num is set
            if self._fbg_num_per_ch == 0:
                self._fbg_num_per_ch = max(1, params.basic.point_num_per_scan // 50)
                self.valid_fbg_label.setText(str(self._fbg_num_per_ch))

        log.info(f"Parameters: scan_rate={params.basic.scan_rate}, points={params.basic.point_num_per_scan}, "
                 f"channels={params.upload.channel_num}, data_source={params.upload.data_source}, "
                 f"fbg_num={self._fbg_num_per_ch}, frames={params.display.frame_num}")

        # Start data saver
        if params.save.enable:
            self.data_saver = FrameBasedFileSaver(
                params.save.path,
                frames_per_file=params.save.frames_per_file,
                buffer_size=OPTIMIZED_BUFFER_SIZES['storage_queue_frames']
            )
            filename = self.data_saver.start(
                scan_rate=params.basic.scan_rate,
                points_per_frame=self._fbg_num_per_ch
            )
            self.save_status_label.setText(f"Save: {filename}")
        else:
            self.save_status_label.setText("Save: Off")

        # Reset counters
        self._data_count = 0
        self._gui_update_count = 0
        self._raw_data_count = 0
        self._last_data_time = time.time()
        self._last_raw_display_time = 0

        # Create acquisition thread
        if self.simulation_mode:
            self.acq_thread = SimulatedAcquisitionThread(self)
        else:
            self.acq_thread = AcquisitionThread(self.api, self)

        self.acq_thread.configure(params, self._fbg_num_per_ch)

        self.acq_thread.phase_data_ready.connect(self._on_phase_data)
        self.acq_thread.data_ready.connect(self._on_raw_data)
        self.acq_thread.monitor_data_ready.connect(self._on_monitor_data)
        self.acq_thread.buffer_status.connect(self._on_buffer_status)
        self.acq_thread.error_occurred.connect(self._on_error)
        self.acq_thread.acquisition_stopped.connect(self._on_acquisition_stopped)

        # 连接FFT工作线程信号
        self.fft_worker.fft_ready.connect(self._on_fft_ready)
        self.fft_worker.error_occurred.connect(self._on_fft_error)

        self.acq_thread.start()

        self._set_start_btn_running()
        self._set_stop_btn_enabled()
        self._set_params_enabled(False)
        self.spectrum_analyzer.reset()

        log.info("Acquisition started successfully")

    @pyqtSlot()
    def _on_stop(self):
        log.info("=== STOP button clicked ===")

        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stopping...")

        if self.acq_thread is not None:
            self.acq_thread.stop()

        # 停止FFT工作线程
        if self.fft_worker is not None:
            self.fft_worker.stop()

        if not self.simulation_mode and self.api is not None:
            try:
                self.api.stop()
            except Exception as e:
                log.warning(f"Error stopping device: {e}")

        if self.data_saver is not None:
            try:
                self.data_saver.stop()
            except Exception as e:
                log.warning(f"Error stopping data saver: {e}")
            self.data_saver = None

        self.save_status_label.setText("Save: Off")
        self.stop_btn.setText("STOP")

    @pyqtSlot()
    def _on_acquisition_stopped(self):
        self._set_start_btn_ready()
        self._set_stop_btn_disabled()
        self._set_params_enabled(True)

    def _set_params_enabled(self, enabled: bool):
        for widget in [self.clk_internal_radio, self.clk_external_radio,
                       self.trig_in_radio, self.trig_out_radio,
                       self.scan_rate_spin, self.pulse_width_spin,
                       self.point_num_spin, self.bypass_spin, self.center_freq_combo,
                       self.channel_combo, self.data_source_combo,
                       self.detrend_bw_spin, self.polar_div_check,
                       self.amp_base_spin, self.fbg_interval_spin, self.get_peak_btn]:
            widget.setEnabled(enabled)

    # ----- DATA SIGNAL HANDLERS -----

    @pyqtSlot(np.ndarray, int)
    def _on_phase_data(self, data: np.ndarray, channel_num: int):
        self._data_count += 1

        if self.data_saver is not None and self.data_saver.is_running:
            self.data_saver.save_frame(data)
            if self._data_count % 20 == 0:
                frame_info = f"{self.data_saver.frame_count}/{self.data_saver.frames_per_file}"
                self.save_status_label.setText(f"Save: #{self.data_saver.file_no} {frame_info}")

        try:
            self._update_phase_display(data, channel_num)
            self._gui_update_count += 1
        except Exception as e:
            log.exception(f"Error in _update_phase_display: {e}")

    @pyqtSlot(np.ndarray, int, int)
    def _on_raw_data(self, data: np.ndarray, data_type: int, channel_num: int):
        """
        处理Raw数据信号，应用新的优化策略:
        - 数据已在采集线程中限制为前4帧
        - 应用新的更新间隔控制
        """
        self._data_count += 1
        self._raw_data_count += 1

        # 数据保存（如果启用）
        if self.data_saver is not None and self.data_saver.is_running:
            self.data_saver.save_frame(data)

        # 使用新的显示更新逻辑（内部有间隔控制）
        try:
            self._update_raw_display(data, channel_num)
            self._gui_update_count += 1
        except Exception as e:
            log.exception(f"Error in _update_raw_display: {e}")

        # 更新统计信息（每10次更新一次）
        if self._raw_data_count % 10 == 0:
            log.debug(f"Raw data processed: count={self._raw_data_count}, "
                     f"data_shape={data.shape}, channels={channel_num}")

    @pyqtSlot(np.ndarray, int)
    def _on_monitor_data(self, data: np.ndarray, channel_num: int):
        self._current_monitor_data = data
        try:
            self._update_monitor_display(data, channel_num)
        except Exception as e:
            log.exception(f"Error in _update_monitor_display: {e}")

    @pyqtSlot(int, int)
    def _on_buffer_status(self, points: int, mb: int):
        self.buffer_label.setText(f"Buffer: {mb} MB")

    @pyqtSlot(str)
    def _on_error(self, message: str):
        log.error(f"Acquisition error: {message}")
        self.statusBar.showMessage(f"Error: {message}", 5000)

    @pyqtSlot(np.ndarray, np.ndarray, float)
    def _on_fft_ready(self, freq: np.ndarray, spectrum: np.ndarray, df: float):
        """处理FFT计算完成的结果"""
        try:
            self._display_fft_result(freq, spectrum, df)
            log.debug(f"FFT result displayed: {len(freq)} points")
        except Exception as e:
            log.exception(f"Error displaying FFT result: {e}")

    @pyqtSlot(str)
    def _on_fft_error(self, message: str):
        """处理FFT计算错误"""
        log.error(f"FFT calculation error: {message}")
        self.statusBar.showMessage(f"FFT Error: {message}", 3000)

    def _display_fft_result(self, freq: np.ndarray, spectrum: np.ndarray, df: float):
        """显示FFT计算结果"""
        try:
            self.plot_widget_2.setLogMode(x=False, y=False)

            # 滤波有效频率范围
            nyquist = self._sample_rate / 2 if hasattr(self, '_sample_rate') else 500e6
            valid_indices = (freq >= 1.0) & (freq <= nyquist)

            freq_filtered = freq[valid_indices]
            spectrum_filtered = spectrum[valid_indices]

            if len(freq_filtered) > 0:
                # 频率显示为MHz
                freq_display = freq_filtered / 1e6
                self.spectrum_curve.setData(freq_display, spectrum_filtered)

                self.plot_widget_2.enableAutoRange(axis='x')
                self.plot_widget_2.setLabel('bottom', 'Frequency (MHz)',
                                          **{'font-family': 'Times New Roman', 'font-size': '12pt'})

                if self.params.display.psd_enable:
                    self.plot_widget_2.setLabel('left', 'PSD (dB/Hz)',
                                              **{'font-family': 'Times New Roman', 'font-size': '12pt'})
                else:
                    self.plot_widget_2.setLabel('left', 'Power (dB)',
                                              **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        except Exception as e:
            log.warning(f"FFT display error: {e}")

    # ----- DISPLAY UPDATE -----

    def _update_phase_display(self, data: np.ndarray, channel_num: int):
        frame_num = self.params.display.frame_num
        fbg_num = self._fbg_num_per_ch

        if fbg_num == 0:
            return

        # Apply rad conversion for display if enabled (storage data remains original)
        display_data = data
        if self.params.display.rad_enable:
            display_data = data.astype(np.float64) / 32767.0 * np.pi

        # Check which tab is currently active for performance optimization
        current_tab = self.plot_tabs.currentIndex() if hasattr(self, 'plot_tabs') else 0

        if self.params.display.mode == DisplayMode.SPACE:
            region_idx = min(self.params.display.region_index, fbg_num - 1)

            if channel_num == 1:
                space_data = []
                for i in range(frame_num):
                    idx = region_idx + fbg_num * i
                    if idx < len(display_data):
                        space_data.append(display_data[idx])
                space_data = np.array(space_data)

                # Update Tab1 (traditional plots) only if it's active or if no tabs
                if current_tab == 0 or current_tab is None:
                    self.plot_curve_1[0].setData(space_data)
                    for i in range(1, 4):
                        self.plot_curve_1[i].setData([])

                    if self.params.display.spectrum_enable and len(space_data) > 0:
                        self._update_spectrum(space_data, self.params.basic.scan_rate,
                                             self.params.display.psd_enable, 'int')

                # Update Tab2 (time-space plot) if it's active and widget exists
                if current_tab == 1 and hasattr(self, 'time_space_widget'):
                    # Send data to time-space widget
                    self.time_space_widget.update_data(display_data, channel_num)
            else:
                if len(display_data.shape) == 1:
                    display_data = display_data.reshape(-1, channel_num)

                # Update Tab1 only if it's active
                if current_tab == 0 or current_tab is None:
                    for ch in range(min(channel_num, 2)):
                        space_data = []
                        for i in range(frame_num):
                            idx = region_idx + fbg_num * i
                            if idx < len(display_data):
                                space_data.append(display_data[idx, ch])
                        self.plot_curve_1[ch].setData(np.array(space_data))
                    for i in range(channel_num, 4):
                        self.plot_curve_1[i].setData([])

                # Update Tab2 if it's active and widget exists
                if current_tab == 1 and hasattr(self, 'time_space_widget'):
                    self.time_space_widget.update_data(display_data, channel_num)
        else:
            # Time mode: overlay multiple frames
            if channel_num == 1:
                # Update Tab1 only if it's active
                if current_tab == 0 or current_tab is None:
                    for i in range(min(4, frame_num)):
                        start = i * fbg_num
                        end = start + fbg_num
                        if end <= len(display_data):
                            self.plot_curve_1[i].setData(display_data[start:end])
                        else:
                            self.plot_curve_1[i].setData([])

                    if self.params.display.spectrum_enable and fbg_num <= len(display_data):
                        self._update_spectrum(display_data[:fbg_num], self.params.basic.scan_rate,
                                             self.params.display.psd_enable, 'int')

                # Update Tab2 if it's active and widget exists
                if current_tab == 1 and hasattr(self, 'time_space_widget'):
                    self.time_space_widget.update_data(display_data, channel_num)
            else:
                if len(display_data.shape) == 1:
                    display_data = display_data.reshape(-1, channel_num)

                # Update Tab1 only if it's active
                if current_tab == 0 or current_tab is None:
                    for ch in range(min(channel_num, 4)):
                        if fbg_num <= len(display_data):
                            self.plot_curve_1[ch].setData(display_data[:fbg_num, ch])

                # Update Tab2 if it's active and widget exists
                if current_tab == 1 and hasattr(self, 'time_space_widget'):
                    self.time_space_widget.update_data(display_data, channel_num)

        if self.acq_thread is not None:
            self.frames_label.setText(f"Frames: {self.acq_thread.frames_acquired}")

    def _update_raw_display(self, data: np.ndarray, channel_num: int):
        """
        更新Raw数据显示，实现新的优化显示机制:
        1. 单通道：4帧平均显示，可选FFT
        2. 双通道：分别显示每通道4帧平均，禁用FFT
        3. 时域图更新间隔至少1秒
        4. FFT更新间隔至少3秒
        """
        current_time = time.time()
        point_num = self.params.basic.point_num_per_scan

        # 检查时域图更新间隔
        time_domain_interval = RAW_DATA_CONFIG['time_domain_update_s']
        if (current_time - self._last_time_domain_update) < time_domain_interval:
            return

        log.debug(f"Updating raw display: data_shape={data.shape}, channels={channel_num}")

        try:
            if channel_num == 1:
                # 单通道模式
                averaged_frame = self._compute_averaged_frame(data, point_num)
                if averaged_frame is not None:
                    # 生成x轴数据（从0开始）
                    x_axis = np.arange(len(averaged_frame))
                    self.plot_curve_1[0].setData(x_axis, averaged_frame)
                    # 清空其他曲线
                    for i in range(1, 4):
                        self.plot_curve_1[i].setData([])

                    log.debug(f"Single channel: averaged {len(data)//point_num} frames, "
                             f"display {len(averaged_frame)} points")

                # FFT处理（如果启用且间隔满足）
                fft_interval = RAW_DATA_CONFIG['fft_update_s']
                if (self.params.display.spectrum_enable and
                    (current_time - self._last_fft_update) >= fft_interval):

                    # 使用单帧原始数据计算FFT（1GHz采样率）
                    single_frame = data[:point_num]
                    self.fft_worker.calculate_fft(single_frame, self.params.display.psd_enable)
                    self._last_fft_update = current_time
                    log.debug("FFT calculation requested")

            elif channel_num == 2:
                # 双通道模式：第一通道显示在时域图，第二通道显示在FFT图位置
                if len(data.shape) == 1:
                    data = data.reshape(-1, channel_num)

                # 第一通道显示在时域图（plot_widget_1）
                ch0_data = data[:, 0]
                averaged_frame_ch0 = self._compute_averaged_frame(ch0_data, point_num, single_channel=True)
                if averaged_frame_ch0 is not None:
                    # 生成x轴数据（从0开始）
                    x_axis = np.arange(len(averaged_frame_ch0))
                    self.plot_curve_1[0].setData(x_axis, averaged_frame_ch0)
                    # 清空其他时域曲线
                    for i in range(1, 4):
                        self.plot_curve_1[i].setData([])

                # 第二通道显示在FFT图位置（plot_widget_2）
                ch1_data = data[:, 1]
                averaged_frame_ch1 = self._compute_averaged_frame(ch1_data, point_num, single_channel=True)
                if averaged_frame_ch1 is not None:
                    # 生成x轴数据（从0开始）
                    x_axis = np.arange(len(averaged_frame_ch1))
                    self.spectrum_curve.setData(x_axis, averaged_frame_ch1)

                    # 设置FFT图为时域显示模式
                    self.plot_widget_2.setLogMode(x=False, y=False)
                    self.plot_widget_2.enableAutoRange()
                    self.plot_widget_2.setLabel('bottom', 'Sample Index',
                                              **{'font-family': 'Times New Roman', 'font-size': '12pt'})
                    self.plot_widget_2.setLabel('left', 'Amplitude (Channel 2)',
                                              **{'font-family': 'Times New Roman', 'font-size': '12pt'})

                log.debug(f"Dual channel: ch0 on time domain plot, ch1 on spectrum plot")

            self._last_time_domain_update = current_time

        except Exception as e:
            log.exception(f"Error in _update_raw_display: {e}")

        # 更新帧计数显示
        if self.acq_thread is not None:
            self.frames_label.setText(f"Frames: {self.acq_thread.frames_acquired}")

    def _compute_averaged_frame(self, data: np.ndarray, point_num: int, single_channel: bool = False) -> Optional[np.ndarray]:
        """
        计算4帧平均数据

        Args:
            data: 输入数据
            point_num: 每帧点数
            single_channel: 是否为单通道数据

        Returns:
            平均后的数据，如果数据不足则返回None
        """
        try:
            if single_channel:
                # 单通道数据处理
                total_points = len(data)
                available_frames = total_points // point_num
            else:
                # 可能是多维数据
                if len(data.shape) > 1:
                    total_points = data.shape[0]
                else:
                    total_points = len(data)
                available_frames = total_points // point_num

            if available_frames < 1:
                log.warning(f"Insufficient data for frame averaging: {total_points} points, need {point_num}")
                return None

            # 最多使用4帧进行平均
            frames_to_use = min(available_frames, 4)

            if single_channel or len(data.shape) == 1:
                # 一维数据
                frames = []
                for i in range(frames_to_use):
                    start = i * point_num
                    end = start + point_num
                    frames.append(data[start:end])
            else:
                # 多维数据（应该不会到达这里，但保险起见）
                frames = []
                for i in range(frames_to_use):
                    start = i * point_num
                    end = start + point_num
                    frames.append(data[start:end, 0])  # 取第一列

            # 计算平均并取整
            frames_array = np.array(frames)
            averaged = np.mean(frames_array, axis=0)
            return averaged.astype(np.int32)  # 取整数

        except Exception as e:
            log.exception(f"Error computing averaged frame: {e}")
            return None

    def _update_monitor_display(self, data: np.ndarray, channel_num: int):
        fbg_num = self._fbg_num_per_ch
        if fbg_num == 0:
            return

        if channel_num == 1:
            self.monitor_curves[0].setData(data[:fbg_num])
            self.monitor_curves[1].setData([])
        else:
            if len(data.shape) == 1:
                data = data.reshape(-1, channel_num)
            for ch in range(min(channel_num, 2)):
                self.monitor_curves[ch].setData(data[:fbg_num, ch])

    def _update_spectrum(self, data: np.ndarray, sample_rate: float, psd_mode: bool, data_type: str):
        try:
            freq, spectrum, df = self.spectrum_analyzer.update(data, sample_rate, psd_mode, data_type)

            self.plot_widget_2.setLogMode(x=False, y=False)

            nyquist = sample_rate / 2
            if data_type == 'int':
                valid_indices = (freq >= 1.0) & (freq <= nyquist)
            else:
                valid_indices = (freq >= 0) & (freq <= nyquist)

            freq_filtered = freq[valid_indices]
            spectrum_filtered = spectrum[valid_indices]

            if len(freq_filtered) > 0:
                if data_type == 'int':
                    freq_display = freq_filtered
                else:
                    freq_display = freq_filtered / 1e6

                self.spectrum_curve.setData(freq_display, spectrum_filtered)

                if data_type == 'int':
                    self.plot_widget_2.setXRange(1.0, nyquist, padding=0.02)
                    self.plot_widget_2.setLabel('bottom', 'Frequency (Hz)',
                                              **{'font-family': 'Times New Roman', 'font-size': '12pt'})
                else:
                    self.plot_widget_2.enableAutoRange(axis='x')
                    self.plot_widget_2.setLabel('bottom', 'Frequency (MHz)',
                                              **{'font-family': 'Times New Roman', 'font-size': '12pt'})

            if psd_mode:
                self.plot_widget_2.setLabel('left', 'PSD (dB/Hz)',
                                          **{'font-family': 'Times New Roman', 'font-size': '12pt'})
            else:
                self.plot_widget_2.setLabel('left', 'Power (dB)',
                                          **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        except Exception as e:
            log.warning(f"Spectrum update error: {e}")

    # ----- STATUS MONITORING -----

    def _update_status(self):
        self._update_calculated_values()

        if self.acq_thread is not None and self.acq_thread.is_running:
            self.frames_label.setText(f"Frames: {self.acq_thread.frames_acquired}")
            if hasattr(self.acq_thread, '_current_polling_interval'):
                polling_ms = self.acq_thread._current_polling_interval * 1000
                self.polling_label.setText(f"Poll: {polling_ms:.1f}ms")
        else:
            self.frames_label.setText("Frames: 0")
            self.polling_label.setText("Poll: --ms")

        self._update_file_estimates()

    def _update_calculated_values(self):
        point_num = self.point_num_spin.value()
        scan_rate = self.scan_rate_spin.value()
        channel_num = self.channel_combo.currentData() or 1

        data_rate_mbps = calculate_data_rate_mbps(scan_rate, point_num, channel_num)
        self._data_rate_label.setText(f"Data Rate: {data_rate_mbps:.1f} MB/s")

        fiber_length = calculate_fiber_length(point_num)
        self._fiber_length_label.setText(f"Fiber: {fiber_length:.2f} km")

    def _on_data_source_changed(self, index: int):
        data_source = self.data_source_combo.currentData()
        is_phase = (data_source == DataSource.PHASE)

        self.plot_widget_3.setEnabled(is_phase)
        self.mode_space_radio.setEnabled(is_phase)

        if not is_phase:
            self.mode_time_radio.setChecked(True)

        self._update_calculated_values()

    def _on_channel_changed(self, index: int):
        """处理通道数量变化，控制FFT功能可用性"""
        channel_num = self.channel_combo.currentData() or 1
        data_source = self.data_source_combo.currentData() or DataSource.RAW

        # Raw数据模式下的FFT控制逻辑
        if data_source in [DataSource.RAW, DataSource.AMPLITUDE]:
            is_single_channel = (channel_num == 1)

            # 双通道时禁用spectrum相关选项
            self.spectrum_enable_check.setEnabled(is_single_channel)
            self.psd_check.setEnabled(is_single_channel)

            if not is_single_channel:
                # 双通道时强制关闭spectrum选项
                self.spectrum_enable_check.setChecked(False)
                log.debug("Dual channel mode: FFT disabled, Ch2 will display on spectrum plot")
            else:
                log.debug("Single channel mode: FFT available on spectrum plot")

            # FFT子图始终可见（双通道时用于显示第二通道）
            if hasattr(self, 'plot_widget_2'):
                self.plot_widget_2.setVisible(True)

        self._update_calculated_values()

    def _browse_save_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.save_path_edit.text())
        if path:
            self.save_path_edit.setText(path)

    def _update_file_estimates(self):
        try:
            frames_per_file = self.frames_per_file_spin.value()
            channel_num = self.channel_combo.currentData() or 1
            fbg_num = self._fbg_num_per_ch if self._fbg_num_per_ch > 0 else 100

            frame_size_mb = fbg_num * channel_num * 4 / (1024 * 1024)
            file_size_mb = frame_size_mb * frames_per_file

            self.file_size_label.setText(f"~{file_size_mb:.1f}MB/file")
        except Exception:
            self.file_size_label.setText("~?MB/file")

    def _update_system_status(self):
        try:
            current_time = time.time()
            if current_time - self._last_system_update < MONITOR_UPDATE_INTERVALS['system_status_s']:
                return
            self._last_system_update = current_time

            self._cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_label.setText(f"CPU: {self._cpu_percent:.1f}%")

            if self.data_saver and self.data_saver.is_running:
                save_path = self.save_path_edit.text()
                if os.path.exists(save_path):
                    _, _, free_bytes = shutil.disk_usage(save_path)
                    self._disk_free_gb = free_bytes / (1024**3)
                    self.disk_label.setText(f"Disk: {self._disk_free_gb:.1f}GB free")
        except Exception as e:
            log.warning(f"Error updating system status: {e}")

    # ----- APPLICATION LIFECYCLE -----

    def closeEvent(self, event):
        log.info("Window closing...")

        if self.acq_thread is not None and self.acq_thread.isRunning():
            self.acq_thread.stop()
            if not self.acq_thread.wait(2000):
                self.acq_thread.terminate()
                self.acq_thread.wait(1000)

        if self.data_saver is not None:
            try:
                self.data_saver.stop()
            except Exception as e:
                log.warning(f"Error stopping data saver: {e}")

        if self.api is not None:
            try:
                self.api.close()
            except Exception as e:
                log.warning(f"Error closing device: {e}")

        log.info("Window closed")
        event.accept()
