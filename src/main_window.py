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
    QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QFont, QPixmap
import pyqtgraph as pg

from config import (
    AllParams, BasicParams, UploadParams, PhaseDemodParams, PeakDetectionParams,
    DisplayParams, SaveParams,
    ClockSource, TriggerDirection, DataSource, DisplayMode,
    CHANNEL_NUM_OPTIONS, DATA_SOURCE_OPTIONS, CENTER_FREQ_OPTIONS,
    validate_point_num, calculate_fiber_length, calculate_data_rate_mbps,
    OPTIMIZED_BUFFER_SIZES, MONITOR_UPDATE_INTERVALS
)
from wfbg7825_api import WFBG7825API, WFBG7825Error
from acquisition_thread import AcquisitionThread, SimulatedAcquisitionThread
from data_saver import FrameBasedFileSaver
from spectrum_analyzer import RealTimeSpectrumAnalyzer
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

        # System monitoring
        self._last_system_update = 0
        self._cpu_percent = 0.0
        self._disk_free_gb = 0.0

        # Setup UI
        self.setWindowTitle("eDAS-fs-7825 gh.26.2.15")
        self.setMinimumSize(1400, 950)

        self._setup_ui()
        self._setup_plots()
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

        # Row 3: Center Freq
        basic_layout.addWidget(QLabel("CenterFreq:"), 3, 0, 1, 2)
        self.center_freq_combo = QComboBox()
        for label, value in CENTER_FREQ_OPTIONS:
            self.center_freq_combo.addItem(label, value)
        self.center_freq_combo.setCurrentIndex(1)  # Default 200MHz
        self.center_freq_combo.setMinimumHeight(INPUT_MIN_HEIGHT)
        basic_layout.addWidget(self.center_freq_combo, 3, 2, 1, 2)

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
        upload_layout.addWidget(self.data_source_combo, 0, 1)

        upload_layout.addWidget(QLabel("Channels:"), 0, 2)
        self.channel_combo = QComboBox()
        for label, value in CHANNEL_NUM_OPTIONS:
            self.channel_combo.addItem(label, value)
        self.channel_combo.setMinimumHeight(INPUT_MIN_HEIGHT)
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

        # Get Peak Info button
        self.get_peak_btn = QPushButton("Get Peak Info")
        self.get_peak_btn.setMinimumHeight(28)
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

        # Peak count labels
        peak_layout.addWidget(QLabel("CH0 Peaks:"), 2, 0)
        self.ch0_peak_label = QLabel("0")
        self.ch0_peak_label.setStyleSheet("font-weight: bold; color: #1f77b4;")
        peak_layout.addWidget(self.ch0_peak_label, 2, 1)

        peak_layout.addWidget(QLabel("CH1 Peaks:"), 2, 2)
        self.ch1_peak_label = QLabel("0")
        self.ch1_peak_label.setStyleSheet("font-weight: bold; color: #ff7f0e;")
        peak_layout.addWidget(self.ch1_peak_label, 2, 3)

        peak_layout.addWidget(QLabel("Valid FBG:"), 3, 0)
        self.valid_fbg_label = QLabel("0")
        self.valid_fbg_label.setStyleSheet("font-weight: bold; color: #2ca02c;")
        peak_layout.addWidget(self.valid_fbg_label, 3, 1)

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
        self.start_btn.setMinimumHeight(38)
        self._set_start_btn_ready()

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setMinimumHeight(38)
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
        layout.setSpacing(10)
        layout.setContentsMargins(5, 5, 5, 10)

        pg.setConfigOptions(antialias=True)

        self.plot_widget_1 = pg.PlotWidget(title="Time Domain / Phase Data")
        self.plot_widget_2 = pg.PlotWidget(title="FFT Spectrum")
        self.plot_widget_3 = pg.PlotWidget(title="Monitor (FBG Amplitude)")

        for pw in [self.plot_widget_1, self.plot_widget_2, self.plot_widget_3]:
            pw.setBackground('w')
            pw.showGrid(x=True, y=True, alpha=0.6)
            x_axis = pw.getAxis('bottom')
            y_axis = pw.getAxis('left')
            x_axis.setStyle(showValues=True, tickLength=5, tickTextOffset=15)
            y_axis.setStyle(showValues=True, tickLength=5, tickTextOffset=8)
            pw.getPlotItem().getViewBox().setBackgroundColor('w')
            pw.getAxis('left').setPen('k')
            pw.getAxis('bottom').setPen('k')
            pw.getAxis('left').setTextPen('k')
            pw.getAxis('bottom').setTextPen('k')
            font = QFont("Times New Roman", 12)
            pw.getAxis('left').setTickFont(font)
            pw.getAxis('bottom').setTickFont(font)

        self.plot_widget_1.setLabel('left', 'Amplitude', **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        self.plot_widget_1.setLabel('bottom', 'Sample', **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        self.plot_curve_1 = []

        self.plot_widget_2.setLabel('left', 'Power', units='dB', **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        self.plot_widget_2.setLabel('bottom', 'Frequency', units='Hz', **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        self.plot_widget_2.setLogMode(x=False, y=False)
        self.spectrum_curve = self.plot_widget_2.plot(pen=pg.mkPen('#9467bd', width=1.5))

        self.plot_widget_3.setLabel('left', 'Amplitude', **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        self.plot_widget_3.setLabel('bottom', 'FBG Index', **{'font-family': 'Times New Roman', 'font-size': '12pt'})
        self.monitor_curves = []

        for pw, min_h, max_h in [(self.plot_widget_1, 180, 210),
                                  (self.plot_widget_2, 180, 210),
                                  (self.plot_widget_3, 130, 160)]:
            pw.setMinimumHeight(min_h)
            pw.setMaximumHeight(max_h)
            pw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout.addWidget(self.plot_widget_1)
        layout.addWidget(self.plot_widget_2)
        layout.addWidget(self.plot_widget_3)

        layout.addStretch(1)

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

    def _setup_plots(self):
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']

        for i in range(4):
            curve = self.plot_widget_1.plot(pen=pg.mkPen(colors[i], width=1.5))
            self.plot_curve_1.append(curve)

        for i in range(2):
            curve = self.plot_widget_3.plot(pen=pg.mkPen(colors[i], width=1.5))
            self.monitor_curves.append(curve)

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
        self._data_count += 1
        self._raw_data_count += 1

        if self.data_saver is not None and self.data_saver.is_running:
            self.data_saver.save_frame(data)

        current_time = time.time()
        if (current_time - self._last_raw_display_time) >= 1.0:
            try:
                self._update_raw_display(data, channel_num)
                self._gui_update_count += 1
                self._last_raw_display_time = current_time
            except Exception as e:
                log.exception(f"Error in _update_raw_display: {e}")

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

    # ----- DISPLAY UPDATE -----

    def _update_phase_display(self, data: np.ndarray, channel_num: int):
        frame_num = self.params.display.frame_num
        fbg_num = self._fbg_num_per_ch

        if fbg_num == 0:
            return

        if self.params.display.mode == DisplayMode.SPACE:
            region_idx = min(self.params.display.region_index, fbg_num - 1)

            if channel_num == 1:
                space_data = []
                for i in range(frame_num):
                    idx = region_idx + fbg_num * i
                    if idx < len(data):
                        space_data.append(data[idx])
                space_data = np.array(space_data)
                self.plot_curve_1[0].setData(space_data)
                for i in range(1, 4):
                    self.plot_curve_1[i].setData([])

                if self.params.display.spectrum_enable and len(space_data) > 0:
                    self._update_spectrum(space_data, self.params.basic.scan_rate,
                                         self.params.display.psd_enable, 'int')
            else:
                if len(data.shape) == 1:
                    data = data.reshape(-1, channel_num)
                for ch in range(min(channel_num, 2)):
                    space_data = []
                    for i in range(frame_num):
                        idx = region_idx + fbg_num * i
                        if idx < len(data):
                            space_data.append(data[idx, ch])
                    self.plot_curve_1[ch].setData(np.array(space_data))
                for i in range(channel_num, 4):
                    self.plot_curve_1[i].setData([])
        else:
            # Time mode: overlay multiple frames
            if channel_num == 1:
                for i in range(min(4, frame_num)):
                    start = i * fbg_num
                    end = start + fbg_num
                    if end <= len(data):
                        self.plot_curve_1[i].setData(data[start:end])
                    else:
                        self.plot_curve_1[i].setData([])

                if self.params.display.spectrum_enable and fbg_num <= len(data):
                    self._update_spectrum(data[:fbg_num], self.params.basic.scan_rate,
                                         self.params.display.psd_enable, 'int')
            else:
                if len(data.shape) == 1:
                    data = data.reshape(-1, channel_num)
                for ch in range(min(channel_num, 4)):
                    if fbg_num <= len(data):
                        self.plot_curve_1[ch].setData(data[:fbg_num, ch])

        if self.acq_thread is not None:
            self.frames_label.setText(f"Frames: {self.acq_thread.frames_acquired}")

    def _update_raw_display(self, data: np.ndarray, channel_num: int):
        point_num = self.params.basic.point_num_per_scan
        frame_num = self.params.display.frame_num

        if channel_num == 1:
            for i in range(min(4, frame_num)):
                start = i * point_num
                end = start + point_num
                if end <= len(data):
                    raw_frame = data[start:end]
                    downsampled = raw_frame[::10]
                    self.plot_curve_1[i].setData(downsampled)
                else:
                    self.plot_curve_1[i].setData([])

            if self.params.display.spectrum_enable and point_num <= len(data):
                sample_rate = 1e9  # Fixed 1GSps
                self._update_spectrum(data[:point_num], sample_rate,
                                     self.params.display.psd_enable, 'short')
        else:
            if len(data.shape) == 1:
                data = data.reshape(-1, channel_num)
            for ch in range(min(channel_num, 4)):
                if point_num <= len(data):
                    raw_channel = data[:point_num, ch]
                    downsampled = raw_channel[::10]
                    self.plot_curve_1[ch].setData(downsampled)

            if self.params.display.spectrum_enable and point_num <= len(data):
                sample_rate = 1e9
                self._update_spectrum(data[:point_num, 0], sample_rate,
                                     self.params.display.psd_enable, 'short')

        if self.acq_thread is not None:
            self.frames_label.setText(f"Frames: {self.acq_thread.frames_acquired}")

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
