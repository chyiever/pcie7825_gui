"""
Time-Space Plot Widget for WFBG-7825

PyQt5 widget for 2D time-space visualization of DAS phase data.
Implements rolling window display with configurable parameters.

Based on PlotWidget+ImageItem approach for reliable axis control.
Adapted from example project's TimeSpacePlotWidgetV2 implementation.
"""

import numpy as np
from collections import deque
from typing import Optional, Tuple, Dict, Any
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QSpinBox, QDoubleSpinBox, QComboBox, QPushButton,
    QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5 import QtCore
from PyQt5.QtGui import QFont
import pyqtgraph as pg

from logger import get_logger

# Module logger
log = get_logger("time_space_plot")

# Available colormap options for PyQtGraph
COLORMAP_OPTIONS = [
    ("Jet", "jet"),
    ("HSV", "hsv"),
    ("Viridis", "viridis"),
    ("Plasma", "plasma"),
    ("Inferno", "inferno"),
    ("Magma", "magma"),
    ("Seismic", "seismic"),
    ("Gray", "gray"),
    ("Hot", "hot"),
    ("Cool", "cool")
]


class TimeSpacePlotWidget(QWidget):
    """
    Time-Space plot widget based on PlotWidget+ImageItem.

    Provides reliable 2D time-space visualization with full axis control.
    Adapted from example project for WFBG-7825 DAS system.
    """

    # Signals
    pointCountChanged = pyqtSignal(int)
    plotStateChanged = pyqtSignal(bool)

    def __init__(self):
        """Initialize the time-space plot widget."""
        super().__init__()
        log.debug("Initializing TimeSpacePlotWidget with PlotWidget+ImageItem")

        # Data buffer and parameters
        self._data_buffer = None
        self._max_window_frames = 100
        self._window_frames = 5
        self._distance_start = 40
        self._distance_end = 100
        self._time_downsample = 5  # 降低默认时间下采样，从50改为5
        self._space_downsample = 2
        self._colormap = "jet"
        self._vmin = -0.02
        self._vmax = 0.02

        # Display parameters
        self._full_point_num = 0
        self._current_frame_count = 0
        self._plot_enabled = False
        self._pending_update = False
        self._update_interval_ms = 100
        self._scan_rate = 2000  # Default scan rate

        # Timers
        self._display_timer = QTimer()
        self._display_timer.timeout.connect(self._process_pending_update)

        self._setup_ui()
        log.debug("TimeSpacePlotWidget initialized successfully")

    def _setup_ui(self):
        """Setup the widget UI layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)

        # Create control panel
        control_panel = self._create_control_panel()
        control_panel.setMaximumHeight(120)
        layout.addWidget(control_panel)

        # Create plot area
        self._create_plot_area()
        layout.addWidget(self.plot_area_widget, 1)

        # Set size policy to allow expansion
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _create_control_panel(self) -> QGroupBox:
        """Create the control panel with parameter controls."""
        group = QGroupBox("Time-Space Plot Controls")

        # Set font for the group box
        font = QFont("Times New Roman", 9)
        group.setFont(font)

        # Use grid layout for compact arrangement
        layout = QGridLayout(group)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 15, 10, 10)

        # Row 0: Distance Range + Window Frames + Time Downsample + Space Downsample
        row = 0

        # Distance Range controls (adapted for FBG Index)
        distance_label = QLabel("FBG Range:")
        distance_label.setFont(QFont("Times New Roman", 8))
        distance_label.setMinimumHeight(22)
        layout.addWidget(distance_label, row, 0)

        from_label = QLabel("From:")
        from_label.setFont(QFont("Times New Roman", 8))
        layout.addWidget(from_label, row, 1)

        self.distance_start_spin = QSpinBox()
        self.distance_start_spin.setRange(0, 1000000)
        self.distance_start_spin.setValue(self._distance_start)
        self.distance_start_spin.setSuffix("")
        self.distance_start_spin.setMaximumWidth(80)
        self.distance_start_spin.setMinimumHeight(22)
        self.distance_start_spin.setFont(QFont("Times New Roman", 8))
        self.distance_start_spin.valueChanged.connect(self._on_distance_start_changed)
        layout.addWidget(self.distance_start_spin, row, 2)

        to_label = QLabel("To:")
        to_label.setFont(QFont("Times New Roman", 8))
        layout.addWidget(to_label, row, 3)

        self.distance_end_spin = QSpinBox()
        self.distance_end_spin.setRange(1, 1000000)
        self.distance_end_spin.setValue(self._distance_end)
        self.distance_end_spin.setSuffix("")
        self.distance_end_spin.setMaximumWidth(80)
        self.distance_end_spin.setMinimumHeight(22)
        self.distance_end_spin.setFont(QFont("Times New Roman", 8))
        self.distance_end_spin.valueChanged.connect(self._on_distance_end_changed)
        layout.addWidget(self.distance_end_spin, row, 4)

        # Window Frames controls
        frames_label = QLabel("Window Frames:")
        frames_label.setFont(QFont("Times New Roman", 8))
        frames_label.setMinimumHeight(22)
        layout.addWidget(frames_label, row, 5)

        self.window_frames_spin = QSpinBox()
        self.window_frames_spin.setRange(1, 50)
        self.window_frames_spin.setValue(self._window_frames)
        self.window_frames_spin.setMaximumWidth(60)
        self.window_frames_spin.setMinimumHeight(22)
        self.window_frames_spin.setFont(QFont("Times New Roman", 8))
        self.window_frames_spin.valueChanged.connect(self._on_window_frames_changed)
        layout.addWidget(self.window_frames_spin, row, 6)

        # Time Downsample controls
        time_ds_label = QLabel("Time DS:")
        time_ds_label.setFont(QFont("Times New Roman", 8))
        time_ds_label.setMinimumHeight(22)
        layout.addWidget(time_ds_label, row, 7)

        self.time_downsample_spin = QSpinBox()
        self.time_downsample_spin.setRange(1, 1000)
        self.time_downsample_spin.setValue(5)  # 默认值从50改为5
        self.time_downsample_spin.setMaximumWidth(70)
        self.time_downsample_spin.setMinimumHeight(22)
        self.time_downsample_spin.setFont(QFont("Times New Roman", 8))
        self.time_downsample_spin.valueChanged.connect(self._on_time_downsample_changed)
        layout.addWidget(self.time_downsample_spin, row, 8)

        # Space Downsample controls
        space_ds_label = QLabel("Space DS:")
        space_ds_label.setFont(QFont("Times New Roman", 8))
        space_ds_label.setMinimumHeight(22)
        layout.addWidget(space_ds_label, row, 9)

        self.space_downsample_spin = QSpinBox()
        self.space_downsample_spin.setRange(1, 100)
        self.space_downsample_spin.setValue(self._space_downsample)
        self.space_downsample_spin.setMaximumWidth(60)
        self.space_downsample_spin.setMinimumHeight(22)
        self.space_downsample_spin.setFont(QFont("Times New Roman", 8))
        self.space_downsample_spin.valueChanged.connect(self._on_space_downsample_changed)
        layout.addWidget(self.space_downsample_spin, row, 10)

        # Row 1: Color Range + Colormap + Reset Button + PLOT Button
        row = 1

        # Color Range controls
        color_range_label = QLabel("Color Range:")
        color_range_label.setFont(QFont("Times New Roman", 8))
        color_range_label.setMinimumHeight(22)
        layout.addWidget(color_range_label, row, 0)

        min_label = QLabel("Min:")
        min_label.setFont(QFont("Times New Roman", 8))
        layout.addWidget(min_label, row, 1)

        self.vmin_spin = QDoubleSpinBox()
        self.vmin_spin.setRange(-10.0, 10.0)
        self.vmin_spin.setSingleStep(0.01)
        self.vmin_spin.setDecimals(3)
        self.vmin_spin.setValue(self._vmin)
        self.vmin_spin.setMaximumWidth(80)
        self.vmin_spin.setMinimumHeight(22)
        self.vmin_spin.setFont(QFont("Times New Roman", 8))
        self.vmin_spin.valueChanged.connect(self._on_vmin_changed)
        layout.addWidget(self.vmin_spin, row, 2)

        max_label = QLabel("Max:")
        max_label.setFont(QFont("Times New Roman", 8))
        layout.addWidget(max_label, row, 3)

        self.vmax_spin = QDoubleSpinBox()
        self.vmax_spin.setRange(-10.0, 10.0)
        self.vmax_spin.setSingleStep(0.01)
        self.vmax_spin.setDecimals(3)
        self.vmax_spin.setValue(self._vmax)
        self.vmax_spin.setMaximumWidth(80)
        self.vmax_spin.setMinimumHeight(22)
        self.vmax_spin.setFont(QFont("Times New Roman", 8))
        self.vmax_spin.valueChanged.connect(self._on_vmax_changed)
        layout.addWidget(self.vmax_spin, row, 4)

        # Colormap selection
        colormap_label = QLabel("Colormap:")
        colormap_label.setFont(QFont("Times New Roman", 8))
        colormap_label.setMinimumHeight(22)
        layout.addWidget(colormap_label, row, 5)

        self.colormap_combo = QComboBox()
        for display_name, internal_name in COLORMAP_OPTIONS:
            self.colormap_combo.addItem(display_name, internal_name)
        self.colormap_combo.setCurrentText("Jet")
        self.colormap_combo.setMaximumWidth(80)
        self.colormap_combo.setMinimumHeight(22)
        self.colormap_combo.setFont(QFont("Times New Roman", 8))
        self.colormap_combo.currentTextChanged.connect(self._on_colormap_changed)
        layout.addWidget(self.colormap_combo, row, 6)

        # Reset Button
        reset_btn = QPushButton("Reset")
        reset_btn.setFont(QFont("Times New Roman", 8))
        reset_btn.setMaximumWidth(60)
        reset_btn.setMinimumHeight(22)
        reset_btn.clicked.connect(self._reset_to_defaults)
        layout.addWidget(reset_btn, row, 7)

        # PLOT Button
        self.plot_btn = QPushButton("PLOT")
        self.plot_btn.setFont(QFont("Times New Roman", 8, QFont.Bold))
        self.plot_btn.setMaximumWidth(60)
        self.plot_btn.setMinimumHeight(22)
        self.plot_btn.setCheckable(True)
        self.plot_btn.setChecked(False)
        self._update_plot_button_style()
        self.plot_btn.clicked.connect(self._on_plot_button_clicked)
        layout.addWidget(self.plot_btn, row, 8)

        # Add stretch to push everything left
        layout.setColumnStretch(11, 1)

        return group

    def _create_plot_area(self):
        """Create the plot area using PlotWidget+ImageItem with histogram widget."""
        # Create a horizontal layout for plot + histogram
        plot_container = QWidget()
        plot_layout = QHBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(5)

        # Create PlotWidget for full axis control
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumSize(700, 400)  # Slightly smaller to make room for histogram
        self.plot_widget.setBackground('w')

        # Add ImageItem for 2D data display
        self.image_item = pg.ImageItem()
        self.plot_widget.addItem(self.image_item)

        # Set axis labels with proper styling
        self.plot_widget.setLabel('bottom', 'Time (s)', color='k',
                                 **{'font-family': 'Times New Roman', 'font-size': '8pt'})
        self.plot_widget.setLabel('left', 'FBG Index', color='k',
                                 **{'font-family': 'Times New Roman', 'font-size': '8pt'})

        # 设置坐标轴刻度颜色为黑色
        plot_item = self.plot_widget.getPlotItem()
        plot_item.getAxis('bottom').setPen(color='k')
        plot_item.getAxis('left').setPen(color='k')
        plot_item.getAxis('bottom').setTextPen(color='k')
        plot_item.getAxis('left').setTextPen(color='k')

        # Configure view box
        view_box = self.plot_widget.getViewBox()
        view_box.setAspectLocked(False)
        view_box.setMouseEnabled(x=True, y=True)

        # Create HistogramLUTWidget for color control
        self.histogram_widget = pg.HistogramLUTWidget()
        self.histogram_widget.setMinimumWidth(120)
        self.histogram_widget.setMaximumWidth(150)

        # Connect image to histogram
        self.histogram_widget.setImageItem(self.image_item)

        # Configure histogram widget styling AFTER initialization
        try:
            # Force white background using QTimer to ensure components are ready
            QTimer.singleShot(100, self._set_histogram_white_background)

            # Immediate styling attempt
            self._set_histogram_white_background()

        except Exception as e:
            log.debug(f"Could not set histogram styling: {e}")

        # Add widgets to layout
        plot_layout.addWidget(self.plot_widget, 1)  # Plot takes most space
        plot_layout.addWidget(self.histogram_widget, 0)  # Histogram fixed width

        # Set the container as the main plot area
        self.plot_area_widget = plot_container

        # Apply default colormap
        self._apply_colormap()

        log.info("Successfully created PlotWidget+ImageItem with histogram widget")

    def _set_histogram_white_background(self):
        """Set histogram widget background to white - called after initialization"""
        try:
            # Set font first
            if hasattr(self.histogram_widget, 'gradient'):
                self.histogram_widget.gradient.setTickFont(QFont("Times New Roman", 7))

            # 使用更强化的白色背景设置方法
            # 设置主容器样式
            self.histogram_widget.setStyleSheet("""
                QWidget {
                    background-color: white;
                    color: black;
                }
                QGraphicsView {
                    background-color: white;
                    border: none;
                }
                HistogramLUTWidget {
                    background-color: white;
                }
                GraphicsView {
                    background-color: white;
                }
            """)

            # Set all possible background components to white
            components_to_set = []

            # Main histogram ViewBox
            if hasattr(self.histogram_widget, 'vb'):
                components_to_set.append(('histogram.vb', self.histogram_widget.vb))

            # Gradient ViewBox
            if hasattr(self.histogram_widget, 'gradient') and hasattr(self.histogram_widget.gradient, 'vb'):
                components_to_set.append(('gradient.vb', self.histogram_widget.gradient.vb))

            # Histogram plot ViewBox
            if hasattr(self.histogram_widget, 'plot') and hasattr(self.histogram_widget.plot, 'vb'):
                components_to_set.append(('plot.vb', self.histogram_widget.plot.vb))

            # Set background for all components
            for name, component in components_to_set:
                try:
                    if hasattr(component, 'setBackgroundColor'):
                        component.setBackgroundColor('w')
                        log.debug(f"Set white background for {name}")
                except Exception as e:
                    log.debug(f"Could not set background for {name}: {e}")

            # Set main widget background
            if hasattr(self.histogram_widget, 'setBackground'):
                self.histogram_widget.setBackground('w')

            # 设置渐变编辑器背景
            if hasattr(self.histogram_widget, 'gradient'):
                gradient = self.histogram_widget.gradient
                if gradient:
                    gradient.setStyleSheet("background-color: white; color: black;")

            log.debug("Applied comprehensive white background to histogram widget")

        except Exception as e:
            log.debug(f"Error in _set_histogram_white_background: {e}")

    def _apply_colormap(self):
        """Apply the selected colormap to the image item and histogram widget."""
        try:
            # Try to get the colormap - handle different PyQtGraph versions
            try:
                # 使用正确的colormap映射
                colormap = pg.colormap.get(self._colormap)
                log.debug(f"Successfully loaded colormap: {self._colormap}")
            except Exception as e:
                log.debug(f"Could not get colormap {self._colormap}: {e}")
                # Create fallback colormaps
                if self._colormap == "jet":
                    colormap = pg.ColorMap([0, 0.25, 0.5, 0.75, 1],
                                         [[0, 0, 128, 255], [0, 0, 255, 255], [0, 255, 255, 255],
                                          [255, 255, 0, 255], [255, 0, 0, 255]])
                elif self._colormap == "viridis":
                    colormap = pg.ColorMap([0, 0.25, 0.5, 0.75, 1],
                                         [[68, 1, 84, 255], [71, 44, 122, 255], [59, 81, 139, 255],
                                          [44, 123, 142, 255], [33, 144, 141, 255]])
                elif self._colormap == "gray":
                    colormap = pg.ColorMap([0, 1], [[0, 0, 0, 255], [255, 255, 255, 255]])
                else:
                    # Default jet-like colormap
                    colormap = pg.ColorMap([0, 0.25, 0.5, 0.75, 1],
                                         [[0, 0, 128, 255], [0, 0, 255, 255], [0, 255, 255, 255],
                                          [255, 255, 0, 255], [255, 0, 0, 255]])

            # Apply colormap to histogram widget if available
            if hasattr(self, 'histogram_widget') and self.histogram_widget:
                try:
                    # Set the colormap on the histogram gradient
                    gradient = self.histogram_widget.gradient
                    if hasattr(gradient, 'setColorMap'):
                        gradient.setColorMap(colormap)
                        log.debug(f"Applied colormap to histogram gradient: {self._colormap}")
                    else:
                        # Fallback: set lookup table
                        lut = colormap.getLookupTable()
                        if hasattr(gradient, 'setLookupTable'):
                            gradient.setLookupTable(lut)
                except Exception as e:
                    log.debug(f"Could not apply colormap to histogram: {e}")

            # Also apply to image item directly as backup
            if hasattr(self.image_item, 'setColorMap'):
                self.image_item.setColorMap(colormap)
            elif hasattr(self.image_item, 'setLookupTable'):
                lut = colormap.getLookupTable()
                self.image_item.setLookupTable(lut)

            log.debug(f"Applied colormap: {self._colormap}")
        except Exception as e:
            log.warning(f"Could not apply colormap {self._colormap}: {e}")

    # Control event handlers
    def _on_distance_start_changed(self, value):
        self._distance_start = value
        self._update_distance_range()

    def _on_distance_end_changed(self, value):
        self._distance_end = value
        self._update_distance_range()

    def _on_window_frames_changed(self, value):
        self._window_frames = value

    def _on_time_downsample_changed(self, value):
        self._time_downsample = value

    def _on_space_downsample_changed(self, value):
        self._space_downsample = value

    def _on_vmin_changed(self, value):
        self._vmin = value

    def _on_vmax_changed(self, value):
        self._vmax = value

    def _on_colormap_changed(self, text):
        # Find the internal name for the selected display name
        for display_name, internal_name in COLORMAP_OPTIONS:
            if display_name == text:
                self._colormap = internal_name
                break
        self._apply_colormap()

    def _on_plot_button_clicked(self, checked: bool):
        """Handle PLOT button click event."""
        self._plot_enabled = checked
        self._update_plot_button_style()

        # Emit signal to notify main window
        if hasattr(self, 'plotStateChanged'):
            self.plotStateChanged.emit(self._plot_enabled)

        log.info(f"Time-space plot {'enabled' if self._plot_enabled else 'disabled'}")

    def _update_plot_button_style(self):
        """Update PLOT button style based on state."""
        if self._plot_enabled:
            # Green: plotting enabled
            self.plot_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: 1px solid #45a049;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
        else:
            # Gray: plotting disabled
            self.plot_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f0f0f0;
                    color: #333333;
                    border: 1px solid #cccccc;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
            """)

    def _reset_to_defaults(self):
        """Reset all parameters to default values."""
        self._distance_start = 40
        self._distance_end = 100
        self._window_frames = 5
        self._time_downsample = 5  # 重置时也使用新的默认值
        self._space_downsample = 2
        self._vmin = -0.02
        self._vmax = 0.02
        self._colormap = "jet"

        # Update UI controls
        self.distance_start_spin.setValue(self._distance_start)
        self.distance_end_spin.setValue(self._distance_end)
        self.window_frames_spin.setValue(self._window_frames)
        self.time_downsample_spin.setValue(5)  # 重置值也改为5
        self.space_downsample_spin.setValue(self._space_downsample)
        self.vmin_spin.setValue(self._vmin)
        self.vmax_spin.setValue(self._vmax)
        self.colormap_combo.setCurrentText("Jet")

        self._apply_colormap()
        log.info("Reset time-space parameters to defaults")

    def _update_distance_range(self):
        """Update the distance range constraints."""
        # Ensure end > start
        if self._distance_end <= self._distance_start:
            self._distance_end = self._distance_start + 1
            self.distance_end_spin.setValue(self._distance_end)

    def _process_pending_update(self):
        """Process pending display update."""
        if self._pending_update:
            self._pending_update = False
            # Trigger actual plot update if needed

    def update_data(self, data: np.ndarray, channel_num: int = 1) -> bool:
        """
        Update the plot with new phase data.

        Args:
            data: Phase data array, shape=(1, 228352) = (1, fbg_num*frame_num)
            channel_num: Number of channels

        Returns:
            bool: True if update was successful
        """
        try:
            # Check if plotting is enabled
            if not self._plot_enabled:
                log.debug("Plot disabled, skipping data update")
                return False

            # Get FBG parameters from main window
            main_window = self.parent()
            while main_window is not None and not hasattr(main_window, '_fbg_num_per_ch'):
                main_window = main_window.parent()

            if main_window is None or main_window._fbg_num_per_ch == 0:
                log.warning("FBG number not available, skipping time-space plot update")
                return False

            fbg_num = main_window._fbg_num_per_ch
            frame_num = main_window.params.display.frame_num

            # Step 1: Reshape 1D data to 2D structure (fbg_num, frame_num)
            if data.ndim == 1:
                data = data.reshape(1, -1)

            # Verify data size matches expectation
            expected_size = fbg_num * frame_num
            if data.shape[1] != expected_size:
                log.warning(f"Data size mismatch: expected {expected_size}, got {data.shape[1]}")
                return False

            # Reshape to (frame_num, fbg_num) first, then transpose to (fbg_num, frame_num)
            # Data layout: [f0_fbg0, f0_fbg1, ..., f0_fbgN, f1_fbg0, f1_fbg1, ...]
            # Reshape to: [[f0_fbg0, f0_fbg1, ..., f0_fbgN], [f1_fbg0, f1_fbg1, ...], ...]
            phase_2d = data.reshape(frame_num, fbg_num).T  # (fbg_num, frame_num)

            log.debug(f"Reshaped data: {data.shape} -> {phase_2d.shape} (fbg_num={fbg_num}, frame_num={frame_num})")

            # Initialize or update data buffer
            if self._data_buffer is None:
                self._data_buffer = deque(maxlen=self._max_window_frames)

            # Step 4: Add new frame to buffer (will be concatenated horizontally later)
            self._data_buffer.append(phase_2d)
            self._current_frame_count = len(self._data_buffer)

            # Create time-space data from buffer when enough frames available
            if len(self._data_buffer) >= self._window_frames:
                self._update_display()

            return True

        except Exception as e:
            log.error(f"Error updating time-space data: {e}")
            return False

    def _update_display(self):
        """Update the display with processed time-space data."""
        try:
            # Step 4: Concatenate recent frames horizontally
            recent_frames = list(self._data_buffer)[-self._window_frames:]
            concatenated_data = np.hstack(recent_frames)  # (fbg_num, total_time_points)

            log.debug(f"Concatenated {len(recent_frames)} frames: {concatenated_data.shape}")

            # Step 2: Apply spatial range selection
            start_idx = max(0, self._distance_start)
            end_idx = min(concatenated_data.shape[0], self._distance_end)

            if start_idx >= end_idx:
                log.warning(f"Invalid FBG range: {start_idx} >= {end_idx}")
                return

            # Extract FBG range (spatial dimension)
            spatial_windowed = concatenated_data[start_idx:end_idx, :]  # (selected_fbg, total_time)

            # Step 3: Apply downsampling
            space_step = max(1, self._space_downsample)
            time_step = max(1, self._time_downsample)

            # Downsample both dimensions
            downsampled_data = spatial_windowed[::space_step, ::time_step]

            # Ensure minimum size for display
            if downsampled_data.shape[0] < 1 or downsampled_data.shape[1] < 2:
                log.warning(f"Insufficient data for display: {downsampled_data.shape}")
                return

            # Set image data (space=Y, time=X)
            # 注意：PyQtGraph的ImageItem需要转置以获得正确的显示方向
            # 我们的数据是(space, time)，需要转置为(time, space)以正确显示
            display_data_transposed = downsampled_data.T  # (time, space)
            self.image_item.setImage(display_data_transposed, levels=(self._vmin, self._vmax))

            # Update axis scaling
            self._update_axis_labels(concatenated_data.shape)

            log.debug(f"Updated display: concatenated={concatenated_data.shape}, "
                     f"spatial_range=[{start_idx}:{end_idx}], "
                     f"final_display={downsampled_data.shape}")

        except Exception as e:
            log.error(f"Error updating display: {e}")

    def _update_axis_labels(self, concatenated_shape: tuple):
        """Update axis labels and scales based on concatenated data dimensions."""
        try:
            # Get parameters
            main_window = self.parent()
            while main_window is not None and not hasattr(main_window, '_fbg_num_per_ch'):
                main_window = main_window.parent()

            if main_window is None:
                return

            fbg_num = main_window._fbg_num_per_ch
            frame_num = main_window.params.display.frame_num

            # Calculate coordinate ranges
            total_time_points = concatenated_shape[1]  # Total time points after concatenation
            time_duration_s = (total_time_points / frame_num) * (frame_num / self._scan_rate)

            # Apply FBG range (space axis)
            space_start_actual = max(0, self._distance_start)
            space_end_actual = min(fbg_num, self._distance_end)

            # Set image coordinate mapping
            # X-axis: time (从0开始到time_duration_s)
            # Y-axis: space/FBG index (space_start_actual到space_end_actual)
            rect = QtCore.QRectF(0, space_start_actual, time_duration_s,
                               space_end_actual - space_start_actual)
            self.image_item.setRect(rect)

            log.debug(f"Set image coordinates: Time=[0,{time_duration_s:.6f}]s, "
                     f"FBG=[{space_start_actual},{space_end_actual}], "
                     f"concatenated_shape={concatenated_shape}")

        except Exception as e:
            log.warning(f"Error updating axis labels: {e}")

    def get_parameters(self) -> Dict[str, Any]:
        """Get current parameters."""
        return {
            'window_frames': self._window_frames,
            'distance_range_start': self._distance_start,
            'distance_range_end': self._distance_end,
            'time_downsample': self._time_downsample,
            'space_downsample': self._space_downsample,
            'colormap_type': self._colormap,
            'vmin': self._vmin,
            'vmax': self._vmax,
        }

    def set_parameters(self, params: Dict[str, Any]):
        """Set parameters from dictionary."""
        if 'window_frames' in params:
            self.window_frames_spin.setValue(params['window_frames'])
        if 'distance_range_start' in params:
            self.distance_start_spin.setValue(params['distance_range_start'])
        if 'distance_range_end' in params:
            self.distance_end_spin.setValue(params['distance_range_end'])
        if 'time_downsample' in params:
            self.time_downsample_spin.setValue(params['time_downsample'])
        if 'space_downsample' in params:
            self.space_downsample_spin.setValue(params['space_downsample'])
        if 'vmin' in params:
            self.vmin_spin.setValue(params['vmin'])
        if 'vmax' in params:
            self.vmax_spin.setValue(params['vmax'])
        if 'colormap_type' in params:
            for display_name, internal_name in COLORMAP_OPTIONS:
                if internal_name == params['colormap_type']:
                    self.colormap_combo.setCurrentText(display_name)
                    break

    def clear_data(self):
        """Clear all data and reset the display."""
        self._data_buffer = None
        self._current_frame_count = 0
        self.image_item.clear()
        log.debug("TimeSpacePlotWidget data cleared")