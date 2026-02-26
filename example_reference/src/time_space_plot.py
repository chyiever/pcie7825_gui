"""
Time-Space Plot Widget

PyQt5 widget for 2D time-space visualization of DAS phase data.
Implements rolling window display with configurable parameters.

Features:
- Real-time 2D image display with time (X) vs distance (Y) axes
- Rolling window buffer for smooth scrolling effect
- Configurable downsampling for performance optimization
- Customizable color mapping and range
- PyQtGraph PlotWidget for reliable axis rendering

Author: eDAS Development Team
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
    2D Time-Space plot widget with rolling window functionality.

    Based on PlotWidget + ImageItem for reliable axis display.

    Displays phase data as a 2D image where:
    - X-axis: Time (seconds)
    - Y-axis: Distance (spatial points)
    - Color: Phase value

    Features:
    - Real-time 2D image display with configurable rolling window
    - Reliable axis rendering and labeling
    - Configurable downsampling for performance optimization
    - Customizable color mapping and range
    """

    # Signals
    parametersChanged = pyqtSignal()
    pointCountChanged = pyqtSignal(int)
    plotStateChanged = pyqtSignal(bool)

    def __init__(self):
        """Initialize the time-space plot widget."""
        super().__init__()
        log.debug("Initializing TimeSpacePlotWidget")

        # Data buffer and parameters
        self._data_buffer = None
        self._max_window_frames = 100
        self._window_frames = 5
        self._distance_start = 40
        self._distance_end = 100
        self._time_downsample = 50
        self._space_downsample = 2
        self._colormap = "jet"
        self._vmin = -0.1
        self._vmax = 0.1

        # Display parameters
        self._full_point_num = 0
        self._current_frame_count = 0
        self._plot_enabled = False
        self._pending_update = False

        self._setup_ui()
        log.debug("TimeSpacePlotWidget initialized successfully")

    def _setup_ui(self):
        """Setup the widget UI layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)

        # Create control panel with compact height
        control_panel = self._create_control_panel()
        control_panel.setMaximumHeight(120)  # 减小控制面板高度，因为输入框变小了
        layout.addWidget(control_panel)

        # Create plot area
        self._create_plot_area()
        layout.addWidget(self.image_view, 1)  # 给图像视图更多空间权重

        # Set size policy to allow expansion
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _create_control_panel(self) -> QGroupBox:
        """Create the control panel with parameter controls."""
        group = QGroupBox("Time-Space Plot Controls")

        # Set font for the group box
        font = QFont("Times New Roman", 9)  # 调小组标题字体
        group.setFont(font)

        layout = QGridLayout(group)
        layout.setHorizontalSpacing(15)  # 水平间距
        layout.setVerticalSpacing(8)     # 减小垂直间距

        # Row 0: Distance Range + Window Frames + Time Downsample + Space Downsample
        row = 0

        # Distance Range controls
        distance_label = QLabel("Distance Range:")
        distance_label.setFont(QFont("Times New Roman", 8))
        distance_label.setMinimumHeight(22)
        layout.addWidget(distance_label, row, 0)

        from_label = QLabel("From:")
        from_label.setFont(QFont("Times New Roman", 8))
        from_label.setMinimumHeight(22)
        layout.addWidget(from_label, row, 1)

        self.distance_start_spin = QSpinBox()
        self.distance_start_spin.setRange(0, 1000000)  # Increased range
        self.distance_start_spin.setValue(40)           # Updated default value
        self.distance_start_spin.setMaximumWidth(60)    # 更小宽度
        self.distance_start_spin.setMinimumHeight(22)   # 减小高度
        self.distance_start_spin.setFont(QFont("Times New Roman", 8))
        self.distance_start_spin.valueChanged.connect(self._on_distance_start_changed)
        layout.addWidget(self.distance_start_spin, row, 2)

        to_label = QLabel("To:")
        to_label.setFont(QFont("Times New Roman", 8))
        to_label.setMinimumHeight(22)
        layout.addWidget(to_label, row, 3)

        self.distance_end_spin = QSpinBox()
        self.distance_end_spin.setRange(1, 1000000)  # Increased range
        self.distance_end_spin.setValue(100)         # Updated default value
        self.distance_end_spin.setMaximumWidth(60)   # 更小宽度
        self.distance_end_spin.setMinimumHeight(22)  # 减小高度
        self.distance_end_spin.setFont(QFont("Times New Roman", 8))
        self.distance_end_spin.valueChanged.connect(self._on_distance_end_changed)
        layout.addWidget(self.distance_end_spin, row, 4)

        # Window Frames
        window_label = QLabel("Window Frames:")
        window_label.setFont(QFont("Times New Roman", 8))
        window_label.setMinimumHeight(22)
        layout.addWidget(window_label, row, 5)

        self.window_frames_spin = QSpinBox()
        self.window_frames_spin.setRange(1, self._max_window_frames)  # Minimum changed to 1
        self.window_frames_spin.setValue(self._window_frames)
        self.window_frames_spin.setMaximumWidth(50)  # 更小宽度
        self.window_frames_spin.setMinimumHeight(22)
        self.window_frames_spin.setFont(QFont("Times New Roman", 8))
        self.window_frames_spin.valueChanged.connect(self._on_window_frames_changed)
        layout.addWidget(self.window_frames_spin, row, 6)

        # Time Downsample
        time_ds_label = QLabel("Time DS:")
        time_ds_label.setFont(QFont("Times New Roman", 8))
        time_ds_label.setMinimumHeight(22)
        layout.addWidget(time_ds_label, row, 7)

        self.time_downsample_spin = QSpinBox()
        self.time_downsample_spin.setRange(1, 1000)
        self.time_downsample_spin.setValue(self._time_downsample)
        self.time_downsample_spin.setMaximumWidth(50)  # 更小宽度
        self.time_downsample_spin.setMinimumHeight(22)
        self.time_downsample_spin.setFont(QFont("Times New Roman", 8))
        self.time_downsample_spin.valueChanged.connect(self._on_time_downsample_changed)
        layout.addWidget(self.time_downsample_spin, row, 8)

        # Space Downsample
        space_ds_label = QLabel("Space DS:")
        space_ds_label.setFont(QFont("Times New Roman", 8))
        space_ds_label.setMinimumHeight(22)
        layout.addWidget(space_ds_label, row, 9)

        self.space_downsample_spin = QSpinBox()
        self.space_downsample_spin.setRange(1, 100)
        self.space_downsample_spin.setValue(self._space_downsample)
        self.space_downsample_spin.setMaximumWidth(50)  # 更小宽度
        self.space_downsample_spin.setMinimumHeight(22)
        self.space_downsample_spin.setFont(QFont("Times New Roman", 8))
        self.space_downsample_spin.valueChanged.connect(self._on_space_downsample_changed)
        layout.addWidget(self.space_downsample_spin, row, 10)

        # Row 1: Color Range + Colormap + Update Interval + Reset Button
        row = 1

        # Color Range controls
        color_range_label = QLabel("Color Range:")
        color_range_label.setFont(QFont("Times New Roman", 8))
        color_range_label.setMinimumHeight(22)
        layout.addWidget(color_range_label, row, 0)

        min_label = QLabel("Min:")
        min_label.setFont(QFont("Times New Roman", 8))
        min_label.setMinimumHeight(22)
        layout.addWidget(min_label, row, 1)

        self.vmin_spin = QDoubleSpinBox()
        self.vmin_spin.setRange(-1.0, 1.0)           # Smaller range for phase data
        self.vmin_spin.setDecimals(3)                # 3 decimal places for precision
        self.vmin_spin.setSingleStep(0.001)          # Fine adjustment step
        self.vmin_spin.setValue(-0.1)                # Updated default value
        self.vmin_spin.setMaximumWidth(60)           # 更小宽度
        self.vmin_spin.setMinimumHeight(22)          # 减小高度
        self.vmin_spin.setFont(QFont("Times New Roman", 8))
        self.vmin_spin.valueChanged.connect(self._on_vmin_changed)
        layout.addWidget(self.vmin_spin, row, 2)

        max_label = QLabel("Max:")
        max_label.setFont(QFont("Times New Roman", 8))
        max_label.setMinimumHeight(22)
        layout.addWidget(max_label, row, 3)

        self.vmax_spin = QDoubleSpinBox()
        self.vmax_spin.setRange(-1.0, 1.0)           # Smaller range for phase data
        self.vmax_spin.setDecimals(3)                # 3 decimal places for precision
        self.vmax_spin.setSingleStep(0.001)          # Fine adjustment step
        self.vmax_spin.setValue(0.1)                 # Updated default value
        self.vmax_spin.setMaximumWidth(60)           # 更小宽度
        self.vmax_spin.setMinimumHeight(22)          # 减小高度
        self.vmax_spin.setFont(QFont("Times New Roman", 8))
        self.vmax_spin.valueChanged.connect(self._on_vmax_changed)
        layout.addWidget(self.vmax_spin, row, 4)

        # Colormap
        colormap_label = QLabel("Colormap:")
        colormap_label.setFont(QFont("Times New Roman", 8))
        colormap_label.setMinimumHeight(22)
        layout.addWidget(colormap_label, row, 5)

        self.colormap_combo = QComboBox()
        self.colormap_combo.setMaximumWidth(80)      # 调整宽度
        self.colormap_combo.setMinimumHeight(22)
        self.colormap_combo.setFont(QFont("Times New Roman", 8))
        for name, value in COLORMAP_OPTIONS:
            self.colormap_combo.addItem(name, value)
        self.colormap_combo.setCurrentText("Jet")
        self.colormap_combo.currentTextChanged.connect(self._on_colormap_changed)
        layout.addWidget(self.colormap_combo, row, 6)

        # Update Interval
        interval_label = QLabel("Update Interval:")
        interval_label.setFont(QFont("Times New Roman", 8))
        interval_label.setMinimumHeight(22)
        layout.addWidget(interval_label, row, 7)

        self.update_interval_spin = QSpinBox()
        self.update_interval_spin.setRange(50, 5000)  # 50ms to 5s
        self.update_interval_spin.setValue(self._update_interval_ms)
        self.update_interval_spin.setSuffix(" ms")
        self.update_interval_spin.setMaximumWidth(80)
        self.update_interval_spin.setMinimumHeight(22)
        self.update_interval_spin.setFont(QFont("Times New Roman", 8))
        self.update_interval_spin.valueChanged.connect(self._on_update_interval_changed)
        layout.addWidget(self.update_interval_spin, row, 8)

        # Reset Button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setFont(QFont("Times New Roman", 8))
        reset_btn.setMaximumWidth(120)
        reset_btn.setMinimumHeight(22)
        reset_btn.clicked.connect(self._reset_to_defaults)
        layout.addWidget(reset_btn, row, 9, 1, 2)  # 跨两列

        # 添加弹性空间推到左边
        layout.setColumnStretch(11, 1)

        return group

    def _create_plot_area(self):
        """Create the main plot area with ImageView."""
        # Create ImageView for 2D data display
        self.image_view = pg.ImageView()

        # Set minimum size for larger display
        self.image_view.setMinimumSize(800, 400)

        # Configure the image view for proper scaling
        view = self.image_view.getView()
        if view:
            # Allow the image to fill the view regardless of data size
            view.setAspectLocked(False)  # Allow different X/Y scaling to fill widget
            view.setBackgroundColor('w')  # White background for main plot
            # Enable mouse interaction
            view.setMouseEnabled(x=True, y=True)

        # Set colorbar background to white
        colorbar = self.image_view.getHistogramWidget()
        if colorbar and hasattr(colorbar, 'setBackground'):
            colorbar.setBackground('w')

        # Configure histogram widget background
        if hasattr(self.image_view, 'ui') and hasattr(self.image_view.ui, 'histogram'):
            hist_widget = self.image_view.ui.histogram
            if hasattr(hist_widget, 'setBackground'):
                hist_widget.setBackground('w')
            # Set gradient editor background
            if hasattr(hist_widget, 'gradient') and hasattr(hist_widget.gradient, 'setBackground'):
                hist_widget.gradient.setBackground('w')

        # Set up axes labels - use ImageView's built-in methods
        # ImageView automatically handles axis display, we just need to ensure it's enabled
        try:
            # Hide controls that we don't need
            self.image_view.ui.roiBtn.hide()  # Hide ROI button
            self.image_view.ui.menuBtn.hide()  # Hide menu button

            # Initialize with empty data first
            empty_data = np.zeros((10, 10))
            self.image_view.setImage(empty_data, autoRange=True)

            # Set up proper axes after image is loaded - use robust method
            QTimer.singleShot(200, self._setup_axes_robust)

        except Exception as e:
            log.warning(f"Error in basic plot setup: {e}")

        # Apply initial colormap
        self._apply_colormap()

        # Set colorbar background to white
        self._set_colorbar_white_background()

        # Start axis monitoring timer with longer interval
        self._axis_monitor_timer.start(5000)  # Check every 5 seconds

    def update_data(self, data: np.ndarray) -> bool:
        """
        Update the plot with new phase data.

        Args:
            data: Phase data array (2D: frames x points)
                 Shape: (frame_num, point_num)

        Returns:
            True if data was successfully processed and displayed
        """
        try:
            log.debug(f"Received data shape: {data.shape}, dtype: {data.dtype}")

            # Ensure data is 2D (frames x points)
            if data.ndim == 1:
                data = data.reshape(1, -1)

            # Update current dimensions
            frame_count, point_count = data.shape
            if self._full_point_num != point_count:
                self._full_point_num = point_count
                # Emit signal when point count changes
                self.pointCountChanged.emit(point_count)

            log.debug(f"Processing {frame_count} frames with {point_count} points each")

            # Initialize buffer if needed - store complete data blocks, not individual frames
            if self._data_buffer is None:
                self._data_buffer = deque(maxlen=self._window_frames)
                log.debug(f"Initialized data buffer with maxlen={self._window_frames}")

            # Add the entire data block to buffer
            # Each buffer element will be a (frame_count, processed_point_count) array
            processed_data_block = self._process_data_block(data)

            if processed_data_block is not None:
                self._data_buffer.append(processed_data_block)
                log.debug(f"Added data block shape {processed_data_block.shape} to buffer. Buffer size: {len(self._data_buffer)}")

            # Schedule display update with controlled interval
            self._schedule_display_update()
            return True

        except Exception as e:
            log.error(f"Error updating time-space data: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _process_data_block(self, data_block: np.ndarray) -> Optional[np.ndarray]:
        """
        Process a block of frame data with range selection and downsampling.

        Args:
            data_block: 2D array (frames x points)

        Returns:
            Processed 2D array or None if processing failed
        """
        try:
            frame_count, point_count = data_block.shape

            # Apply distance range
            start_idx = max(0, self._distance_start)
            end_idx = min(point_count, self._distance_end)

            if start_idx >= end_idx:
                log.warning(f"Invalid distance range: {start_idx} >= {end_idx}")
                return None

            # Extract distance range for all frames
            range_data = data_block[:, start_idx:end_idx]  # (frames, selected_points)

            # Apply spatial downsampling
            if self._space_downsample > 1:
                range_data = range_data[:, ::self._space_downsample]

            # Apply time downsampling
            if self._time_downsample > 1 and frame_count > self._time_downsample:
                range_data = range_data[::self._time_downsample, :]

            log.debug(f"Processed data block: {data_block.shape} -> {range_data.shape}")
            return range_data

        except Exception as e:
            log.error(f"Error processing data block: {e}")
            return None

    def _schedule_display_update(self):
        """Schedule a display update with controlled interval."""
        if not self._display_timer.isActive():
            # Start timer for next update
            self._display_timer.start(self._update_interval_ms)
            self._pending_update = False
        else:
            # Timer is running, mark that we have pending update
            self._pending_update = True

    def _update_display(self):
        """Update the 2D image display with current buffer data."""
        if not self._data_buffer or len(self._data_buffer) == 0:
            log.debug("No data in buffer for display update")
            return

        try:
            # Concatenate all data blocks in buffer along time axis
            buffer_list = list(self._data_buffer)

            if len(buffer_list) == 0:
                return

            # Each element in buffer_list is a (frames, spatial_points) array
            # Concatenate along time axis to create full time-space data
            time_space_data = np.concatenate(buffer_list, axis=0)  # (total_frames, spatial_points)

            log.debug(f"Concatenated time-space data shape: {time_space_data.shape}")

            # CRITICAL FIX: 根据日志分析，数据已经是(space, time)形状
            # 但坐标映射期望X=time, Y=distance，需要转置以匹配PyQtGraph约定
            # PyQtGraph约定：第一维(行)→Y轴，第二维(列)→X轴

            # 打印转置前的形状
            log.debug(f"Before transpose: time_space_data.shape = {time_space_data.shape}")

            # 当前：time_space_data.shape = (space, time)
            # 需要：display_data.shape = (time, space) 以实现X=time, Y=space的正确映射
            display_data = time_space_data.T  # 转置: (space,time) → (time,space)

            # 打印转置后的形状
            log.debug(f"After transpose: display_data.shape = {display_data.shape}")
            log.debug(f"Transpose verification: original={time_space_data.shape} -> transposed={display_data.shape}")

            log.debug(f"Final display data shape: {display_data.shape} (time x space for correct scrolling)")
            log.debug(f"Data range: [{np.min(display_data):.4f}, {np.max(display_data):.4f}]")

            # Update image view with proper coordinate mapping
            # After transpose: display_data.shape = (time_points, spatial_points)
            # PyQtGraph映射：第一维→Y轴(时间)，第二维→X轴(空间)，但我们用setRect重新定义坐标
            self.image_view.setImage(display_data,
                                   levels=[self._vmin, self._vmax],
                                   autoRange=False,  # Disable auto range to use our coordinate mapping
                                   autoLevels=False)

            # Configure the image view to fill the widget and show axes properly
            view = self.image_view.getView()
            if view:
                view.setAspectLocked(False)  # Allow different X/Y scaling
                view.autoRange()  # Fit to view
                view.setMouseEnabled(x=True, y=True)  # Enable mouse interaction

            # Critical: Ensure axes remain visible after setImage
            self._ensure_axes_after_update()

            # Apply colormap
            self._apply_colormap()

            # Set colorbar background to white after image update
            self._set_colorbar_white_background()

            # Update scale and labels to reflect actual data dimensions
            self._update_axis_labels(display_data.shape)

            log.debug(f"Display updated successfully with data shape {display_data.shape}")

            # If there are pending updates, schedule another one
            if self._pending_update:
                self._pending_update = False
                self._display_timer.start(self._update_interval_ms)

        except Exception as e:
            log.error(f"Error updating display: {e}")
            import traceback
            traceback.print_exc()

    def _set_colorbar_white_background(self):
        """Set colorbar background to white."""
        try:
            # Get histogram widget (colorbar)
            hist_widget = self.image_view.getHistogramWidget()

            if hist_widget is not None:
                # Try multiple approaches to set white background
                if hasattr(hist_widget, 'setBackground'):
                    hist_widget.setBackground('w')

                # Set background via stylesheet
                hist_widget.setStyleSheet("background-color: white;")

                # Set plot item background
                plot_item = hist_widget.plotItem
                if plot_item and hasattr(plot_item, 'getViewBox'):
                    view_box = plot_item.getViewBox()
                    if view_box and hasattr(view_box, 'setBackgroundColor'):
                        view_box.setBackgroundColor('w')

                # Set gradient editor background
                if hasattr(hist_widget, 'gradient'):
                    gradient = hist_widget.gradient
                    if gradient:
                        gradient.setStyleSheet("background-color: white;")

        except Exception as e:
            log.debug(f"Could not set colorbar background: {e}")

    def _setup_axes_robust(self):
        """
        强化的轴配置方法 - 结合多种方法确保坐标轴显示
        """
        try:
            log.debug("Setting up axes with robust method")

            # 1. 首先尝试通过 _get_plot_item_robust 获取 PlotItem
            plot_item = self._get_plot_item_robust()

            if plot_item is not None:
                log.debug("Got PlotItem, configuring axes...")

                # 强制显示坐标轴
                plot_item.showAxis('bottom', show=True)
                plot_item.showAxis('left', show=True)
                plot_item.showAxis('top', show=False)
                plot_item.showAxis('right', show=False)

                # 设置轴标签
                plot_item.setLabel('bottom', 'Distance (points)',
                                 color='k', **{'font-family': 'Times New Roman', 'font-size': '10pt'})
                plot_item.setLabel('left', 'Time (samples)',
                                 color='k', **{'font-family': 'Times New Roman', 'font-size': '10pt'})

                # 配置轴属性
                font = QFont("Times New Roman", 9)
                for axis_name in ['bottom', 'left']:
                    axis = plot_item.getAxis(axis_name)
                    if axis:
                        axis.setTickFont(font)
                        axis.setPen('k')
                        axis.setTextPen('k')
                        axis.setStyle(showValues=True)  # 强制显示数值
                        axis.enableAutoSIPrefix(False)
                        axis.show()
                        # 清除缓存强制重绘
                        axis.picture = None
                        axis.update()

                self._axis_configured = True
                log.info("Robust axis setup completed successfully")
                return True

            # 2. 如果 PlotItem 方法失败，尝试直接通过 ImageView 设置
            log.debug("PlotItem method failed, trying ImageView direct methods")

            # 方法2a: 直接通过ImageView设置标签（如果支持）
            if hasattr(self.image_view, 'setLabel'):
                self.image_view.setLabel('bottom', 'Distance (points)')
                self.image_view.setLabel('left', 'Time (samples)')
                log.debug("Set labels via ImageView.setLabel")

            # 方法2b: 通过view设置
            view = self.image_view.getView()
            if view is not None:
                if hasattr(view, 'setBackgroundColor'):
                    view.setBackgroundColor('w')
                if hasattr(view, 'setMouseEnabled'):
                    view.setMouseEnabled(x=True, y=True)
                if hasattr(view, 'setLabel'):
                    view.setLabel('bottom', 'Distance (points)')
                    view.setLabel('left', 'Time (samples)')
                    log.debug("Set labels via view.setLabel")

            self._axis_configured = True
            log.warning("Partial axis setup completed - may not show full ticks")
            return True

        except Exception as e:
            log.error(f"Robust axis setup failed: {e}")
            self._axis_configured = False
            return False

    def _setup_axes_simple(self):
        """简化的轴配置方法 - 使用ImageView的内置特性"""
        try:
            # 方法1: 直接设置ImageView的轴标签（最简单可靠）
            if hasattr(self.image_view, 'setLabel'):
                self.image_view.setLabel('bottom', 'Distance (points)')
                self.image_view.setLabel('left', 'Time (samples)')

            # 方法2: 通过view访问（备选）
            view = self.image_view.getView()
            if view is not None:
                # 简单设置背景色和鼠标交互
                if hasattr(view, 'setBackgroundColor'):
                    view.setBackgroundColor('w')
                if hasattr(view, 'setMouseEnabled'):
                    view.setMouseEnabled(x=True, y=True)

                # 尝试设置轴标签
                if hasattr(view, 'setLabel'):
                    view.setLabel('bottom', 'Distance (points)')
                    view.setLabel('left', 'Time (samples)')

            # 方法3: 通过ImageView的ui界面（最后尝试）
            if hasattr(self.image_view, 'ui') and hasattr(self.image_view.ui, 'graphicsView'):
                graphics_view = self.image_view.ui.graphicsView
                if hasattr(graphics_view, 'setLabel'):
                    graphics_view.setLabel('bottom', 'Distance (points)')
                    graphics_view.setLabel('left', 'Time (samples)')

            log.debug("Simple axis setup completed")
            self._axis_configured = True

        except Exception as e:
            log.warning(f"Simple axis setup failed: {e}")
            # 如果所有方法都失败，至少记录状态
            self._axis_configured = False

    def _ensure_axes_visible(self):
        """强化的轴可见性检查和恢复"""
        # 如果还没有配置成功，使用强化方法再尝试一次
        if not self._axis_configured:
            log.debug("Axis not configured, attempting robust setup")
            self._setup_axes_robust()

        # 可选：添加调试信息输出
        if hasattr(self, '_debug_counter'):
            self._debug_counter += 1
            if self._debug_counter % 5 == 0:  # 每5次检查输出一次调试信息
                self._debug_axis_state_simple()
        else:
            self._debug_counter = 1

    def _ensure_axes_after_update(self):
        """更新后确保坐标轴可见 - 强化版"""
        # 每次setImage后重新尝试设置轴标签，使用强化方法
        self._setup_axes_robust()

    def _apply_colormap(self):
        """Apply the selected colormap to the image view."""
        try:
            # Use PyQtGraph's built-in colormap
            if self._colormap == "jet":
                # Create a jet-like colormap
                colors = [
                    (0.0, (0, 0, 128)),      # dark blue
                    (0.25, (0, 0, 255)),     # blue
                    (0.5, (0, 255, 255)),    # cyan
                    (0.75, (255, 255, 0)),   # yellow
                    (1.0, (255, 0, 0))       # red
                ]
            elif self._colormap == "viridis":
                colors = [
                    (0.0, (68, 1, 84)),
                    (0.25, (59, 82, 139)),
                    (0.5, (33, 144, 140)),
                    (0.75, (93, 201, 99)),
                    (1.0, (253, 231, 37))
                ]
            elif self._colormap == "plasma":
                colors = [
                    (0.0, (13, 8, 135)),
                    (0.25, (126, 3, 168)),
                    (0.5, (203, 70, 121)),
                    (0.75, (248, 149, 64)),
                    (1.0, (240, 249, 33))
                ]
            elif self._colormap == "hot":
                colors = [
                    (0.0, (0, 0, 0)),        # black
                    (0.33, (255, 0, 0)),     # red
                    (0.66, (255, 255, 0)),   # yellow
                    (1.0, (255, 255, 255))   # white
                ]
            elif self._colormap == "seismic":
                colors = [
                    (0.0, (0, 0, 139)),      # 深蓝色 (负值)
                    (0.25, (0, 100, 255)),   # 蓝色
                    (0.5, (255, 255, 255)),  # 白色 (零值)
                    (0.75, (255, 100, 100)), # 粉红色
                    (1.0, (139, 0, 0))       # 深红色 (正值)
                ]
            elif self._colormap == "gray":
                colors = [
                    (0.0, (0, 0, 0)),        # black
                    (1.0, (255, 255, 255))   # white
                ]
            else:
                # Default to a simple blue-red colormap
                colors = [
                    (0.0, (0, 0, 255)),      # blue
                    (0.5, (0, 255, 0)),      # green
                    (1.0, (255, 0, 0))       # red
                ]

            # Create colormap
            colormap = pg.ColorMap(pos=[c[0] for c in colors],
                                 color=[c[1] for c in colors])

            # Apply to histogram widget
            hist_widget = self.image_view.getHistogramWidget()
            if hist_widget is not None:
                hist_widget.gradient.setColorMap(colormap)

            log.debug(f"Applied colormap: {self._colormap}")

        except Exception as e:
            log.warning(f"Error applying colormap: {e}")
            import traceback
            traceback.print_exc()

    def _get_plot_item_robust(self):
        """
        Robustly get PlotItem from ImageView across different PyQtGraph versions.

        Returns:
            PlotItem or None if not accessible
        """
        plot_item = None

        try:
            # Method 1: Direct view access (newer versions)
            view = self.image_view.getView()
            if view and hasattr(view, 'showAxis'):
                plot_item = view
                log.debug("Got PlotItem via direct view access")
            elif view and hasattr(view, 'getPlotItem'):
                plot_item = view.getPlotItem()
                log.debug("Got PlotItem via view.getPlotItem()")

            # Method 2: UI interface access (fallback)
            if plot_item is None and hasattr(self.image_view, 'ui'):
                graphics_view = getattr(self.image_view.ui, 'graphicsView', None)
                if graphics_view and hasattr(graphics_view, 'getPlotItem'):
                    plot_item = graphics_view.getPlotItem()
                    log.debug("Got PlotItem via UI interface")

            # Method 3: ImageItem parent access (last resort)
            if plot_item is None:
                try:
                    image_item = self.image_view.getImageItem()
                    if image_item and hasattr(image_item, 'getViewBox'):
                        view_box = image_item.getViewBox()
                        if view_box and hasattr(view_box, 'parent'):
                            parent = view_box.parent()
                            if parent and hasattr(parent, 'showAxis'):
                                plot_item = parent
                                log.debug("Got PlotItem via ImageItem parent")
                except Exception as e:
                    log.debug(f"ImageItem parent method failed: {e}")

        except Exception as e:
            log.warning(f"Error getting PlotItem: {e}")

        if plot_item is None:
            log.warning("All methods to get PlotItem failed")
        else:
            log.debug(f"Successfully got PlotItem: {type(plot_item)}")

        return plot_item

    def _update_axis_labels(self, data_shape: tuple):
        """Update axis labels and scales based on data dimensions."""
        try:
            # Get the plot item using robust method
            plot_item = self._get_plot_item_robust()
            if plot_item is None:
                log.warning("Could not get plot item for axis update")
                return

            # CRITICAL: After transpose, display_data.shape = (spatial_points, time_points)
            # But input data_shape is still from original time_space_data: (time_points, spatial_points)
            original_time_points, original_spatial_points = data_shape

            # Calculate actual coordinate ranges
            # X-axis: Time (horizontal) - FIXED to not be affected by time downsampling
            scan_rate_hz = self._scan_rate if self._scan_rate > 0 else 50000  # Default fallback

            # Time duration should be calculated from ORIGINAL frames, not downsampled
            time_duration_s = original_time_points / scan_rate_hz

            # Y-axis: Distance (vertical) - using actual distance range
            distance_start_actual = self._distance_start  # e.g., 40
            distance_step = self._space_downsample  # e.g., 1
            distance_end_actual = distance_start_actual + original_spatial_points * distance_step

            # Set coordinate mapping using setRect to map image coordinates to real coordinates
            # NO transpose: image shape is (time_points, spatial_points)
            # We want: X=time [0, time_duration_s], Y=distance [distance_start, distance_end]
            image_item = self.image_view.getImageItem()
            if image_item:
                # Set rect: (x_start, y_start, width, height) in real coordinates
                rect = QtCore.QRectF(0, distance_start_actual, time_duration_s,
                                   distance_end_actual - distance_start_actual)
                image_item.setRect(rect)
                log.debug(f"Set image rect: X=[0, {time_duration_s:.3f}]s, Y=[{distance_start_actual}, {distance_end_actual}] points")

            # Update axis labels
            plot_item.setLabel('bottom', f'Time (s, total: {time_duration_s:.3f}s)',
                             color='k', **{'font-family': 'Times New Roman', 'font-size': '10pt'})

            plot_item.setLabel('left', f'Distance (points: {distance_start_actual} to {distance_end_actual})',
                             color='k', **{'font-family': 'Times New Roman', 'font-size': '10pt'})

            # Force show axes again (critical after label update)
            plot_item.showAxis('bottom', show=True)
            plot_item.showAxis('left', show=True)

            # Get and configure axes with enhanced visibility settings
            font = QFont("Times New Roman", 9)
            for axis_name in ['bottom', 'left']:
                axis = plot_item.getAxis(axis_name)
                if axis:
                    axis.setTickFont(font)
                    axis.setPen('k')
                    axis.setTextPen('k')
                    axis.setStyle(showValues=True)
                    axis.enableAutoSIPrefix(False)
                    axis.show()

                    # Force tick redraw
                    axis.picture = None
                    axis.update()

            # Set proper view range to match the coordinate mapping
            view = self.image_view.getView()
            if view:
                view.setRange(xRange=[0, time_duration_s],
                            yRange=[distance_start_actual, distance_end_actual],
                            padding=0)  # No extra padding
                view.enableAutoRange(enable=False)  # Disable auto range to maintain fixed scaling

            log.debug(f"Updated axis labels: X=time({time_duration_s:.3f}s, {original_time_points} frames), Y=distance([{distance_start_actual}, {distance_end_actual}] points)")

        except Exception as e:
            log.warning(f"Error updating axis labels: {e}")
            import traceback
            traceback.print_exc()

    def _on_distance_start_changed(self, value: int):
        """Handle distance start change."""
        if value < self._distance_end:
            self._distance_start = value
            self._update_distance_range()
            self.parametersChanged.emit()

    def _on_distance_end_changed(self, value: int):
        """Handle distance end change."""
        if value > self._distance_start:
            self._distance_end = value
            self._update_distance_range()
            self.parametersChanged.emit()

    def _update_distance_range(self):
        """Update the distance range spin box constraints."""
        self.distance_start_spin.setMaximum(self._distance_end - 1)
        self.distance_end_spin.setMinimum(self._distance_start + 1)

        # Update maximum based on current data size
        if self._full_point_num > 0:
            self.distance_end_spin.setMaximum(self._full_point_num)

    def _on_window_frames_changed(self, value: int):
        """Handle window frames change."""
        self._window_frames = value

        # Recreate buffer with new size
        if self._data_buffer is not None:
            old_data = list(self._data_buffer)
            self._data_buffer = deque(old_data, maxlen=value)
            self._update_display()

        self.parametersChanged.emit()

    def _on_space_downsample_changed(self, value: int):
        """Handle space downsampling change."""
        self._space_downsample = value
        # Clear buffer to force reprocessing with new downsampling
        if self._data_buffer is not None:
            self._data_buffer.clear()
        self.parametersChanged.emit()

    def _on_time_downsample_changed(self, value: int):
        """Handle time downsampling change."""
        self._time_downsample = value
        # Clear buffer to force reprocessing with new time downsampling
        if self._data_buffer is not None:
            self._data_buffer.clear()
        self.parametersChanged.emit()

    def _on_update_interval_changed(self, value: int):
        """Handle update interval change."""
        self._update_interval_ms = value
        self.parametersChanged.emit()
        log.debug(f"Update interval changed to {value}ms")

    def _on_colormap_changed(self, text: str):
        """Handle colormap change."""
        # Find the colormap value
        for name, value in COLORMAP_OPTIONS:
            if name == text:
                self._colormap = value
                break

        # Apply the new colormap immediately
        self._apply_colormap()
        self.parametersChanged.emit()

    def _on_vmin_changed(self, value: float):
        """Handle minimum color value change."""
        self._vmin = value
        self._update_display()
        self.parametersChanged.emit()

    def _on_vmax_changed(self, value: float):
        """Handle maximum color value change."""
        self._vmax = value
        self._update_display()
        self.parametersChanged.emit()

    def _reset_to_defaults(self):
        """Reset all parameters to default values."""
        self._window_frames = 5
        self._distance_start = 40     # Updated reset value
        self._distance_end = 100      # Updated reset value
        self._time_downsample = 50
        self._space_downsample = 2
        self._colormap = "jet"
        self._vmin = -0.1             # Updated reset value
        self._vmax = 0.1              # Updated reset value
        self._update_interval_ms = 100  # Reset update interval

        # Update UI controls
        self.window_frames_spin.setValue(self._window_frames)
        self.distance_start_spin.setValue(self._distance_start)
        self.distance_end_spin.setValue(self._distance_end)
        self.time_downsample_spin.setValue(self._time_downsample)
        self.space_downsample_spin.setValue(self._space_downsample)
        self.colormap_combo.setCurrentText("Jet")
        self.vmin_spin.setValue(self._vmin)
        self.vmax_spin.setValue(self._vmax)
        self.update_interval_spin.setValue(self._update_interval_ms)

        # Clear buffer and recreate with default size
        if self._data_buffer is not None:
            self._data_buffer = deque(maxlen=self._window_frames)

        self.parametersChanged.emit()

    def get_parameters(self) -> Dict[str, Any]:
        """
        Get current time-space plot parameters.

        Returns:
            Dictionary with current parameter values
        """
        return {
            'window_frames': self._window_frames,
            'distance_range_start': self._distance_start,
            'distance_range_end': self._distance_end,
            'time_downsample': self._time_downsample,
            'space_downsample': self._space_downsample,
            'colormap_type': self._colormap,
            'vmin': self._vmin,
            'vmax': self._vmax,
            'update_interval_ms': self._update_interval_ms
        }

    def set_parameters(self, params: Dict[str, Any]):
        """
        Set time-space plot parameters.

        Args:
            params: Dictionary with parameter values to set
        """
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
        if 'colormap_type' in params:
            # Find matching colormap name
            for name, value in COLORMAP_OPTIONS:
                if value == params['colormap_type']:
                    self.colormap_combo.setCurrentText(name)
                    break
        if 'vmin' in params:
            self.vmin_spin.setValue(params['vmin'])
        if 'vmax' in params:
            self.vmax_spin.setValue(params['vmax'])
        if 'update_interval_ms' in params:
            self.update_interval_spin.setValue(params['update_interval_ms'])

    def clear_data(self):
        """Clear all data buffers and reset display."""
        if self._data_buffer is not None:
            self._data_buffer.clear()

        # Reset to empty display
        empty_data = np.zeros((10, 10))
        self.image_view.setImage(empty_data, autoRange=True)

        self._current_frame_count = 0
        log.debug("TimeSpacePlotWidget data cleared")


# ========== ALTERNATIVE IMPLEMENTATION USING PLOTWIDGET ==========
#
# 如果 ImageView 的坐标轴问题仍然无法解决，可以使用以下基于 PlotWidget 的实现
# 这个实现保证坐标轴刻度的完全可靠显示
#

class TimeSpacePlotWidgetV2(QWidget):
    """
    基于 PlotWidget + ImageItem 的 Time-Space 图实现

    完全替代 ImageView，确保坐标轴刻度的可靠显示
    这个版本牺牲了 ImageView 的便利性，但提供了完全的轴控制
    """

    # 信号定义
    parametersChanged = pyqtSignal()
    pointCountChanged = pyqtSignal(int)
    plotStateChanged = pyqtSignal(bool)  # 新增：绘图状态变化信号

    def __init__(self):
        """初始化 PlotWidget 版本的 TimeSpacePlot"""
        super().__init__()
        log.debug("Initializing TimeSpacePlotWidgetV2 (PlotWidget-based)")

        # 数据相关参数 (与原版本相同)
        self._data_buffer = None
        self._max_window_frames = 100
        self._window_frames = 5
        self._distance_start = 40
        self._distance_end = 100
        self._time_downsample = 50
        self._space_downsample = 2
        self._colormap = "jet"
        self._vmin = -0.1
        self._vmax = 0.1
        # 显示相关参数
        self._full_point_num = 0
        self._current_frame_count = 0

        # 绘图状态控制（必须在UI创建之前初始化）
        self._plot_enabled = False

        # 定时器 - 移除定时器，改为每帧直接更新
        # 每次update_data调用时直接更新显示，不使用定时器控制
        self._pending_update = False

        self._setup_ui_v2()
        log.debug("TimeSpacePlotWidgetV2 initialized successfully")

    def _setup_ui_v2(self):
        """设置基于 PlotWidget 的UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)

        # 控制面板 (重用原来的方法)
        control_panel = self._create_control_panel_v2()
        control_panel.setMaximumHeight(140)  # 增加高度，从120调整到140
        layout.addWidget(control_panel)

        # 创建水平布局容纳图形和颜色条
        plot_layout = QHBoxLayout()

        # 创建 PlotWidget 替代 ImageView
        self._create_plot_area_v2()
        plot_layout.addWidget(self.plot_widget, 1)  # 给图形更大比重

        # 创建颜色条
        self._create_colorbar_v2()
        plot_layout.addWidget(self.histogram_widget)  # 添加HistogramLUTWidget

        plot_widget = QWidget()
        plot_widget.setLayout(plot_layout)
        layout.addWidget(plot_widget, 1)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _create_plot_area_v2(self):
        """创建基于 PlotWidget 的绘图区域"""
        # 创建 PlotWidget (完整轴支持)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumSize(800, 400)

        # 添加 ImageItem 用于2D数据显示
        self.image_item = pg.ImageItem()
        self.plot_widget.addItem(self.image_item)

        # 完全可靠的轴配置 - 正确的坐标轴定义
        self.plot_widget.setLabel('bottom', 'Time (s)',
                                color='k', **{'font-size': '10pt', 'font-family': 'Times New Roman'})
        self.plot_widget.setLabel('left', 'Distance (points)',
                                color='k', **{'font-size': '10pt', 'font-family': 'Times New Roman'})

        # 确保坐标轴显示
        self.plot_widget.showAxis('bottom', show=True)
        self.plot_widget.showAxis('left', show=True)
        self.plot_widget.showAxis('top', show=False)
        self.plot_widget.showAxis('right', show=False)

        # 轴字体设置
        font = QFont("Times New Roman", 9)
        for axis_name in ['bottom', 'left']:
            axis = self.plot_widget.getAxis(axis_name)
            if axis:
                axis.setTickFont(font)
                axis.setPen('k')
                axis.setTextPen('k')
                axis.setStyle(showValues=True)
                axis.enableAutoSIPrefix(False)

        # 设置背景和鼠标交互
        self.plot_widget.setBackground('w')
        view_box = self.plot_widget.getViewBox()
        view_box.setMouseEnabled(x=True, y=True)
        view_box.setAspectLocked(False)

        # 重要：初始化时禁用自动范围，为后续手动控制做准备
        view_box.enableAutoRange(enable=False)
        view_box.setAutoVisible(x=False, y=False)

        # 创建手动 ColorBar
        self._create_colorbar_v2()

        # 应用初始colormap
        self._apply_colormap_v2()

        log.info("PlotWidget plot area created with guaranteed axis display")

    def _create_colorbar_v2(self):
        """创建包含直方图和亮度/对比度控制的复合颜色条组件"""
        # 使用PyQtGraph的HistogramLUTWidget，它包含：
        # 1. 颜色渐变条（垂直方向）
        # 2. 数据直方图分布
        # 3. 亮度/对比度滑块控制
        self.histogram_widget = pg.HistogramLUTWidget()
        self.histogram_widget.setFixedWidth(90)  # 减小宽度，避免与主图重叠
        self.histogram_widget.setMinimumHeight(400)

        # 从控制面板获取初始颜色范围，不使用自动更新
        # 颜色范围完全由前面板控制
        self.histogram_widget.setLevels(self._vmin, self._vmax)

        # 应用初始颜色映射
        self._apply_initial_colormap_to_histogram()

        # 注意：不连接sigLevelsChanged信号，避免自动更新vmin/vmax
        # 颜色范围完全由控制面板的spinbox控制

        # 设置背景为白色
        self.histogram_widget.setBackground('w')

        # 设置颜色栏刻度字体为Times New Roman
        self._setup_colorbar_font()

        log.debug("HistogramLUTWidget colorbar created (manual control mode)")

    def _setup_colorbar_font(self):
        """设置颜色栏刻度字体为Times New Roman"""
        try:
            if not hasattr(self, 'histogram_widget') or self.histogram_widget is None:
                return

            # Get the plot item from histogram widget
            plot_item = getattr(self.histogram_widget, 'plotItem', None)
            if plot_item is None:
                return

            # Set Times New Roman font for colorbar axis
            font = QFont("Times New Roman", 8)

            # Configure the right axis (y-axis of the colorbar)
            axis = plot_item.getAxis('left')
            if axis:
                axis.setTickFont(font)
                axis.setPen('k')
                axis.setTextPen('k')
                axis.setStyle(showValues=True)
                log.debug("Colorbar font set to Times New Roman")

        except Exception as e:
            log.debug(f"Could not set colorbar font: {e}")

    def _on_plot_button_clicked(self, checked: bool):
        """处理PLOT按钮点击事件"""
        self._plot_enabled = checked
        self._update_plot_button_style()

        # 发射信号通知主窗口
        if hasattr(self, 'plotStateChanged'):
            self.plotStateChanged.emit(self._plot_enabled)

        log.info(f"Time-space plot {'enabled' if self._plot_enabled else 'disabled'}")

    def _update_plot_button_style(self):
        """更新PLOT按钮样式"""
        if self._plot_enabled:
            # 绿色：正在绘图
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
            # 灰色：停止绘图
            self.plot_btn.setStyleSheet("""
                QPushButton {
                    background-color: #9E9E9E;
                    color: white;
                    border: 1px solid #757575;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #757575;
                }
            """)

    def is_plot_enabled(self) -> bool:
        """返回当前绘图状态"""
        return self._plot_enabled

    def _apply_initial_colormap_to_histogram(self):
        """为HistogramLUTWidget应用初始颜色映射"""
        try:
            # 创建颜色映射数组
            if self._colormap == "jet":
                colors = [
                    (0.0, (0, 0, 128)), (0.25, (0, 0, 255)),
                    (0.5, (0, 255, 255)), (0.75, (255, 255, 0)), (1.0, (255, 0, 0))
                ]
            elif self._colormap == "viridis":
                colors = [
                    (0.0, (68, 1, 84)), (0.25, (59, 82, 139)),
                    (0.5, (33, 144, 140)), (0.75, (93, 201, 99)), (1.0, (253, 231, 37))
                ]
            elif self._colormap == "plasma":
                colors = [
                    (0.0, (13, 8, 135)), (0.25, (126, 3, 168)),
                    (0.5, (203, 70, 121)), (0.75, (249, 142, 93)), (1.0, (240, 249, 33))
                ]
            elif self._colormap == "seismic":
                colors = [
                    (0.0, (0, 0, 139)),      # 深蓝色 (负值)
                    (0.25, (0, 100, 255)),   # 蓝色
                    (0.5, (255, 255, 255)),  # 白色 (零值)
                    (0.75, (255, 100, 100)), # 粉红色
                    (1.0, (139, 0, 0))       # 深红色 (正值)
                ]
            else:  # grayscale
                colors = [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))]

            # 设置渐变颜色
            gradient = self.histogram_widget.gradient
            gradient.setColorMap(pg.ColorMap(pos=[c[0] for c in colors],
                                           color=[c[1] for c in colors]))

            log.debug(f"Applied {self._colormap} colormap to histogram widget")

        except Exception as e:
            log.warning(f"Error applying initial colormap to histogram: {e}")


    def _apply_colormap_v2(self):
        """为 PlotWidget 版本应用颜色映射"""
        try:
            # 创建颜色映射 (复用原有逻辑)
            if self._colormap == "jet":
                colors = [
                    (0.0, (0, 0, 128)), (0.25, (0, 0, 255)),
                    (0.5, (0, 255, 255)), (0.75, (255, 255, 0)), (1.0, (255, 0, 0))
                ]
            elif self._colormap == "viridis":
                colors = [
                    (0.0, (68, 1, 84)), (0.25, (59, 82, 139)),
                    (0.5, (33, 144, 140)), (0.75, (93, 201, 99)), (1.0, (253, 231, 37))
                ]
            elif self._colormap == "plasma":
                colors = [
                    (0.0, (13, 8, 135)), (0.25, (126, 3, 168)),
                    (0.5, (203, 70, 121)), (0.75, (248, 149, 64)), (1.0, (240, 249, 33))
                ]
            elif self._colormap == "hot":
                colors = [
                    (0.0, (0, 0, 0)), (0.33, (255, 0, 0)),
                    (0.66, (255, 255, 0)), (1.0, (255, 255, 255))
                ]
            elif self._colormap == "seismic":
                colors = [
                    (0.0, (0, 0, 139)),      # 深蓝色 (负值)
                    (0.25, (0, 100, 255)),   # 蓝色
                    (0.5, (255, 255, 255)),  # 白色 (零值)
                    (0.75, (255, 100, 100)), # 粉红色
                    (1.0, (139, 0, 0))       # 深红色 (正值)
                ]
            elif self._colormap == "gray":
                colors = [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))]
            else:
                colors = [(0.0, (0, 0, 255)), (0.5, (0, 255, 0)), (1.0, (255, 0, 0))]

            colormap = pg.ColorMap(pos=[c[0] for c in colors], color=[c[1] for c in colors])

            # 设置主图像的颜色映射
            lut = colormap.getLookupTable(0.0, 1.0, 256)
            self.image_item.setLookupTable(lut)

            # 更新HistogramLUTWidget的颜色映射
            if hasattr(self, 'histogram_widget'):
                self.histogram_widget.gradient.setColorMap(colormap)

            log.debug(f"Applied colormap to PlotWidget version: {self._colormap}")

        except Exception as e:
            log.warning(f"Error applying colormap in PlotWidget version: {e}")

    def _create_control_panel_v2(self):
        """创建控制面板 - 完整实现"""
        group = QGroupBox()  # 移除标题文字
        group.setFont(QFont("Times New Roman", 9))

        layout = QGridLayout(group)
        layout.setHorizontalSpacing(15)
        layout.setVerticalSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)  # 减少上边距

        # 删除状态指示标签，直接开始第一行控件

        # Row 0: Distance Range + Window Frames + Time Downsample + Space Downsample (上移一行)
        row = 0

        # Distance Range controls
        distance_label = QLabel("Distance Range:")
        distance_label.setFont(QFont("Times New Roman", 8))
        distance_label.setMinimumHeight(22)
        layout.addWidget(distance_label, row, 0)

        from_label = QLabel("From:")
        from_label.setFont(QFont("Times New Roman", 8))
        from_label.setMinimumHeight(22)
        layout.addWidget(from_label, row, 1)

        self.distance_start_spin = QSpinBox()
        self.distance_start_spin.setRange(0, 1000000)
        self.distance_start_spin.setValue(40)
        self.distance_start_spin.setMaximumWidth(60)
        self.distance_start_spin.setMinimumHeight(22)
        self.distance_start_spin.setFont(QFont("Times New Roman", 8))
        self.distance_start_spin.valueChanged.connect(self._on_distance_start_changed_v2)
        layout.addWidget(self.distance_start_spin, row, 2)

        to_label = QLabel("To:")
        to_label.setFont(QFont("Times New Roman", 8))
        to_label.setMinimumHeight(22)
        layout.addWidget(to_label, row, 3)

        self.distance_end_spin = QSpinBox()
        self.distance_end_spin.setRange(1, 1000000)
        self.distance_end_spin.setValue(100)
        self.distance_end_spin.setMaximumWidth(60)
        self.distance_end_spin.setMinimumHeight(22)
        self.distance_end_spin.setFont(QFont("Times New Roman", 8))
        self.distance_end_spin.valueChanged.connect(self._on_distance_end_changed_v2)
        layout.addWidget(self.distance_end_spin, row, 4)

        # Window Frames
        window_label = QLabel("Window Frames:")
        window_label.setFont(QFont("Times New Roman", 8))
        window_label.setMinimumHeight(22)
        layout.addWidget(window_label, row, 5)

        self.window_frames_spin = QSpinBox()
        self.window_frames_spin.setRange(1, self._max_window_frames)
        self.window_frames_spin.setValue(self._window_frames)
        self.window_frames_spin.setMaximumWidth(50)
        self.window_frames_spin.setMinimumHeight(22)
        self.window_frames_spin.setFont(QFont("Times New Roman", 8))
        self.window_frames_spin.valueChanged.connect(self._on_window_frames_changed_v2)
        layout.addWidget(self.window_frames_spin, row, 6)

        # Time Downsample
        time_ds_label = QLabel("Time DS:")
        time_ds_label.setFont(QFont("Times New Roman", 8))
        time_ds_label.setMinimumHeight(22)
        layout.addWidget(time_ds_label, row, 7)

        self.time_downsample_spin = QSpinBox()
        self.time_downsample_spin.setRange(1, 1000)
        self.time_downsample_spin.setValue(self._time_downsample)
        self.time_downsample_spin.setMaximumWidth(50)
        self.time_downsample_spin.setMinimumHeight(22)
        self.time_downsample_spin.setFont(QFont("Times New Roman", 8))
        self.time_downsample_spin.valueChanged.connect(self._on_time_downsample_changed_v2)
        layout.addWidget(self.time_downsample_spin, row, 8)

        # Space Downsample
        space_ds_label = QLabel("Space DS:")
        space_ds_label.setFont(QFont("Times New Roman", 8))
        space_ds_label.setMinimumHeight(22)
        layout.addWidget(space_ds_label, row, 9)

        self.space_downsample_spin = QSpinBox()
        self.space_downsample_spin.setRange(1, 100)
        self.space_downsample_spin.setValue(self._space_downsample)
        self.space_downsample_spin.setMaximumWidth(50)
        self.space_downsample_spin.setMinimumHeight(22)
        self.space_downsample_spin.setFont(QFont("Times New Roman", 8))
        self.space_downsample_spin.valueChanged.connect(self._on_space_downsample_changed_v2)
        layout.addWidget(self.space_downsample_spin, row, 10)

        # Row 1: Color Range + Colormap + Reset Button + PLOT Button (上移一行)
        row = 1

        # Color Range controls
        color_range_label = QLabel("Color Range:")
        color_range_label.setFont(QFont("Times New Roman", 8))
        color_range_label.setMinimumHeight(22)
        layout.addWidget(color_range_label, row, 0)

        min_label = QLabel("Min:")
        min_label.setFont(QFont("Times New Roman", 8))
        min_label.setMinimumHeight(22)
        layout.addWidget(min_label, row, 1)

        self.vmin_spin = QDoubleSpinBox()
        self.vmin_spin.setRange(-10000.0, 10000.0)  # 扩大范围到±10000
        self.vmin_spin.setDecimals(3)
        self.vmin_spin.setSingleStep(0.001)
        self.vmin_spin.setValue(-0.1)
        self.vmin_spin.setMaximumWidth(60)
        self.vmin_spin.setMinimumHeight(22)
        self.vmin_spin.setFont(QFont("Times New Roman", 8))
        self.vmin_spin.valueChanged.connect(self._on_vmin_changed_v2)
        layout.addWidget(self.vmin_spin, row, 2)

        max_label = QLabel("Max:")
        max_label.setFont(QFont("Times New Roman", 8))
        max_label.setMinimumHeight(22)
        layout.addWidget(max_label, row, 3)

        self.vmax_spin = QDoubleSpinBox()
        self.vmax_spin.setRange(-10000.0, 10000.0)  # 扩大范围到±10000
        self.vmax_spin.setDecimals(3)
        self.vmax_spin.setSingleStep(0.001)
        self.vmax_spin.setValue(0.1)
        self.vmax_spin.setMaximumWidth(60)
        self.vmax_spin.setMinimumHeight(22)
        self.vmax_spin.setFont(QFont("Times New Roman", 8))
        self.vmax_spin.valueChanged.connect(self._on_vmax_changed_v2)
        layout.addWidget(self.vmax_spin, row, 4)

        # Colormap
        colormap_label = QLabel("Colormap:")
        colormap_label.setFont(QFont("Times New Roman", 8))
        colormap_label.setMinimumHeight(22)
        layout.addWidget(colormap_label, row, 5)

        self.colormap_combo = QComboBox()
        self.colormap_combo.setMaximumWidth(80)
        self.colormap_combo.setMinimumHeight(22)
        self.colormap_combo.setFont(QFont("Times New Roman", 8))
        for name, value in COLORMAP_OPTIONS:
            self.colormap_combo.addItem(name, value)
        self.colormap_combo.setCurrentText("Jet")
        self.colormap_combo.currentTextChanged.connect(self._on_colormap_changed_v2)
        layout.addWidget(self.colormap_combo, row, 6)

        # Reset Button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setFont(QFont("Times New Roman", 8))
        reset_btn.setMaximumWidth(120)
        reset_btn.setMinimumHeight(22)
        reset_btn.clicked.connect(self._reset_to_defaults_v2)
        layout.addWidget(reset_btn, row, 7)

        # PLOT Button (替代原来的Time-space模式选择)
        self.plot_btn = QPushButton("PLOT")
        self.plot_btn.setFont(QFont("Times New Roman", 8, QFont.Bold))
        self.plot_btn.setMaximumWidth(60)
        self.plot_btn.setMinimumHeight(22)
        self.plot_btn.setCheckable(True)  # 可切换状态
        self.plot_btn.setChecked(False)   # 初始状态：停止
        self._update_plot_button_style()
        self.plot_btn.clicked.connect(self._on_plot_button_clicked)
        layout.addWidget(self.plot_btn, row, 8)

        # 添加弹性空间
        layout.setColumnStretch(11, 1)

        return group

    def update_data_v2(self, data: np.ndarray) -> bool:
        """PlotWidget版本的数据更新方法"""
        try:
            log.debug(f"PlotWidget version received data shape: {data.shape}")

            # 检查绘图是否启用
            if not self._plot_enabled:
                log.debug("Plot disabled, skipping data update")
                return False

            if data.ndim == 1:
                data = data.reshape(1, -1)

            frame_count, point_count = data.shape
            if self._full_point_num != point_count:
                self._full_point_num = point_count
                self.pointCountChanged.emit(point_count)

            # 数据处理 (重用原有逻辑)
            if self._data_buffer is None:
                self._data_buffer = deque(maxlen=self._window_frames)

            processed_data_block = self._process_data_block_v2(data)
            if processed_data_block is not None:
                self._data_buffer.append(processed_data_block)

            # 调度显示更新
            self._schedule_display_update_v2()
            return True

        except Exception as e:
            log.error(f"Error in PlotWidget version update_data: {e}")
            return False

    def _process_data_block_v2(self, data_block: np.ndarray) -> Optional[np.ndarray]:
        """处理数据块 - 重用原有逻辑"""
        try:
            frame_count, point_count = data_block.shape

            # 应用距离范围
            start_idx = max(0, self._distance_start)
            end_idx = min(point_count, self._distance_end)

            if start_idx >= end_idx:
                return None

            range_data = data_block[:, start_idx:end_idx]

            # 应用降采样
            if self._space_downsample > 1:
                range_data = range_data[:, ::self._space_downsample]

            if self._time_downsample > 1 and frame_count > self._time_downsample:
                range_data = range_data[::self._time_downsample, :]

            return range_data

        except Exception as e:
            log.error(f"Error processing data block in PlotWidget version: {e}")
            return None

    def _schedule_display_update_v2(self):
        """直接更新显示，不使用定时器控制"""
        # 改为每帧直接更新，不使用定时器延迟
        self._update_display_v2()

    def _update_display_v2(self):
        """PlotWidget版本的显示更新 - 正确的坐标轴定义"""
        if not self._data_buffer or len(self._data_buffer) == 0:
            return

        try:
            # 合并缓冲区数据 - 确保时间顺序正确
            buffer_list = list(self._data_buffer)
            time_space_data = np.concatenate(buffer_list, axis=0)

            log.debug(f"PlotWidget updating display with data shape: {time_space_data.shape}")
            log.debug(f"Data buffer length: {len(self._data_buffer)}, window_frames: {self._window_frames}")

            # 重要：重新分析坐标轴映射
            # 原始数据: (time_frames, space_points)
            # 我们的目标: Y轴=distance, X轴=time
            #
            # PyQtGraph ImageItem的坐标系统：
            # - 第一个维度对应Y轴(垂直方向)
            # - 第二个维度对应X轴(水平方向)
            #
            # 所以如果原始数据是 (time_frames, space_points)
            # 要实现 Y轴=distance, X轴=time，我们需要转置！

            # 尝试不转置，看看效果
            # display_data = time_space_data  # 不转置：(time_frames, space_points)
            # 这样的话：Y轴=time, X轴=space，这不是我们要的

            # 不需要转置！因为在_update_display中已经转置过了
            # time_space_data已经经过第一次转置，现在应该是(time, space)形状
            display_data = time_space_data  # 直接使用，不再转置

            log.debug(f"PlotWidget V2: received data shape: {time_space_data.shape}")
            log.debug(f"PlotWidget V2: using data without additional transpose")

            log.debug(f"Time-space data shape after processing: {display_data.shape} (should be time x space)")
            log.debug(f"Display data range: [{np.min(display_data):.3f}, {np.max(display_data):.3f}]")

            # 设置图像数据
            self.image_item.setImage(display_data, levels=[self._vmin, self._vmax])

            # 连接数据到HistogramLUTWidget以显示直方图分布
            if hasattr(self, 'histogram_widget'):
                self.histogram_widget.setImageItem(self.image_item)
                # 设置颜色范围，这会更新直方图的显示范围
                self.histogram_widget.setLevels(self._vmin, self._vmax)

            # 获取数据维度 - 现在应该是(time, space)
            n_time_points, n_spatial_points = display_data.shape  # time在Y方向，space在X方向

            # 计算实际坐标范围
            distance_start = self._distance_start
            distance_end = self._distance_end

            # X轴: 时间范围计算 - 重要：不受time DS影响
            try:
                from config import AllParams
                config = AllParams()
                scan_rate_hz = config.basic.scan_rate  # Hz
            except:
                scan_rate_hz = 2000  # 默认值

            # 计算实际时间长度：应该基于原始帧数，不是降采样后的帧数
            original_time_points = time_space_data.shape[0]  # 原始时间帧数
            current_displayed_time_points = display_data.shape[1]  # 当前显示的时间点数

            # 实际时间长度应该基于缓冲区中的总帧数，不受降采样影响
            time_duration_s = original_time_points / scan_rate_hz

            log.debug(f"Time calculation: original_frames={original_time_points}, "
                     f"displayed_frames={current_displayed_time_points}, "
                     f"time_duration={time_duration_s:.3f}s, scan_rate={scan_rate_hz}Hz")

            # 计算实际的坐标范围
            distance_start = self._distance_start
            distance_end = self._distance_end

            # 获取处理后的数据维度
            n_spatial_points, n_time_points_displayed = display_data.shape

            # 设置图像边界 - 映射到实际坐标范围
            # 注意：时间轴应该映射到实际时间，空间轴映射到实际距离
            self.image_item.setRect(pg.QtCore.QRectF(
                0, distance_start,  # 起始位置: (时间=0, 距离=distance_start)
                time_duration_s, distance_end - distance_start  # 宽度=实际时间长度, 高度=距离范围
            ))

            log.debug(f"Image rect set: X=[0, {time_duration_s:.3f}s], Y=[{distance_start}, {distance_end}]")

            # X轴: 时间范围 [0, duration]，单位秒
            # 从配置获取scan_rate，如果没有则使用默认值
            try:
                from config import AllParams
                config = AllParams()
                scan_rate_hz = config.basic.scan_rate  # Hz
            except:
                scan_rate_hz = 2000  # 默认值

            # 计算时间长度：帧数 / 扫描频率
            # 重要：使用original_time_points而不是n_time_points，确保时间范围不受降采样影响
            time_duration_s = original_time_points / scan_rate_hz

            # 设置ViewBox范围 - 强制Y轴从distance_start开始
            view_box = self.plot_widget.getViewBox()

            # 禁用自动缩放，强制使用指定范围
            view_box.enableAutoRange(enable=False)
            view_box.setAutoVisible(x=False, y=False)

            # X轴：时间范围 [0, time_duration_s]，无冗余
            view_box.setXRange(0, time_duration_s, padding=0)

            # Y轴：距离范围 [distance_start, distance_end]，无冗余 - 强制设置
            view_box.setYRange(distance_start, distance_end, padding=0)

            # 额外确保范围设置
            view_box.setLimits(xMin=0, xMax=time_duration_s,
                              yMin=distance_start, yMax=distance_end)

            # 设置自定义刻度标签 - 强制使用实际坐标值
            self._setup_custom_ticks_v2_corrected(
                distance_start, distance_end, time_duration_s
            )

            # 强制禁用自动刻度，确保使用我们的自定义刻度
            bottom_axis = self.plot_widget.getAxis('bottom')
            left_axis = self.plot_widget.getAxis('left')
            if bottom_axis:
                bottom_axis.enableAutoSIPrefix(False)
            if left_axis:
                left_axis.enableAutoSIPrefix(False)

            # 更新轴标签 - 正确的定义
            self.plot_widget.setLabel('bottom', f'Time (s, total: {time_duration_s:.1f}s)')
            self.plot_widget.setLabel('left', f'Distance (points: {distance_start} to {distance_end})')

            # 应用颜色映射
            self._apply_colormap_v2()

            # 更新颜色条范围
            self._update_colorbar_range()

            log.debug("PlotWidget display updated with corrected axes (Y=distance, X=time)")

        except Exception as e:
            log.error(f"Error updating PlotWidget display: {e}")
            import traceback
            traceback.print_exc()

    def _setup_custom_ticks_v2_corrected(self, distance_start, distance_end, time_duration_s):
        """设置正确的自定义刻度标签 - 使用实际坐标值"""
        try:
            # Y轴刻度：显示实际距离值 (distance range)
            left_axis = self.plot_widget.getAxis('left')
            if left_axis:
                # 自动生成距离刻度
                distance_range = distance_end - distance_start
                # 根据范围大小决定刻度间隔
                if distance_range <= 20:
                    tick_step = 2
                elif distance_range <= 50:
                    tick_step = 5
                elif distance_range <= 100:
                    tick_step = 10
                else:
                    tick_step = distance_range // 10

                tick_positions = []
                tick_labels = []

                # 生成从distance_start到distance_end的刻度
                for dist in range(distance_start, distance_end + 1, tick_step):
                    if dist <= distance_end:
                        tick_positions.append(dist)
                        tick_labels.append(str(dist))

                # 确保起始和结束位置有刻度
                if distance_start not in tick_positions:
                    tick_positions.insert(0, distance_start)
                    tick_labels.insert(0, str(distance_start))
                if distance_end not in tick_positions:
                    tick_positions.append(distance_end)
                    tick_labels.append(str(distance_end))

                # 设置Y轴自定义刻度 - 位置就是实际距离值
                ticks_y = list(zip(tick_positions, tick_labels))
                left_axis.setTicks([ticks_y])

            # X轴刻度：显示时间(秒)
            bottom_axis = self.plot_widget.getAxis('bottom')
            if bottom_axis:
                tick_positions = []
                tick_labels = []

                # 根据时间长度决定刻度间隔
                if time_duration_s <= 1:
                    tick_step = 0.1  # 0.1秒间隔
                elif time_duration_s <= 5:
                    tick_step = 0.5  # 0.5秒间隔
                elif time_duration_s <= 10:
                    tick_step = 1.0  # 1秒间隔
                else:
                    tick_step = time_duration_s / 10  # 10个刻度

                # 生成时间刻度
                current_time = 0
                while current_time <= time_duration_s:
                    tick_positions.append(current_time)
                    tick_labels.append(f"{current_time:.1f}")
                    current_time += tick_step

                # 确保结束时间有刻度
                if time_duration_s not in tick_positions:
                    tick_positions.append(time_duration_s)
                    tick_labels.append(f"{time_duration_s:.1f}")

                ticks_x = list(zip(tick_positions, tick_labels))
                bottom_axis.setTicks([ticks_x])

            log.debug(f"Set corrected ticks: Y={len(ticks_y)} distance ticks [{distance_start}-{distance_end}], X={len(ticks_x)} time ticks [0-{time_duration_s:.1f}s]")

        except Exception as e:
            log.warning(f"Error setting corrected custom ticks: {e}")

    def _update_colorbar_range(self):
        """更新HistogramLUTWidget的颜色范围"""
        try:
            if hasattr(self, 'histogram_widget'):
                # 更新HistogramLUTWidget的颜色范围
                self.histogram_widget.setLevels(self._vmin, self._vmax)

                log.debug(f"Updated histogram widget range: [{self._vmin}, {self._vmax}]")

        except Exception as e:
            log.warning(f"Error updating histogram widget range: {e}")

    # ========== V2版本的参数变化处理方法 ==========

    def _on_distance_start_changed_v2(self, value: int):
        """处理距离起始值变化"""
        if value < self._distance_end:
            self._distance_start = value
            self._update_distance_range_v2()
            self.parametersChanged.emit()

    def _on_distance_end_changed_v2(self, value: int):
        """处理距离结束值变化"""
        if value > self._distance_start:
            self._distance_end = value
            self._update_distance_range_v2()
            self.parametersChanged.emit()

    def _update_distance_range_v2(self):
        """更新距离范围约束"""
        self.distance_start_spin.setMaximum(self._distance_end - 1)
        self.distance_end_spin.setMinimum(self._distance_start + 1)
        if self._full_point_num > 0:
            self.distance_end_spin.setMaximum(self._full_point_num)

    def _on_window_frames_changed_v2(self, value: int):
        """处理窗口帧数变化"""
        self._window_frames = value
        if self._data_buffer is not None:
            old_data = list(self._data_buffer)
            self._data_buffer = deque(old_data, maxlen=value)
            self._update_display_v2()
        self.parametersChanged.emit()

    def _on_space_downsample_changed_v2(self, value: int):
        """处理空间降采样变化"""
        self._space_downsample = value
        if self._data_buffer is not None:
            self._data_buffer.clear()
        self.parametersChanged.emit()

    def _on_time_downsample_changed_v2(self, value: int):
        """处理时间降采样变化"""
        self._time_downsample = value
        if self._data_buffer is not None:
            self._data_buffer.clear()
        self.parametersChanged.emit()

        log.debug(f"Update interval changed to {value}ms")

    def _on_colormap_changed_v2(self, text: str):
        """处理颜色映射变化"""
        for name, value in COLORMAP_OPTIONS:
            if name == text:
                self._colormap = value
                break
        self._apply_colormap_v2()
        self.parametersChanged.emit()

    def _on_vmin_changed_v2(self, value: float):
        """处理最小颜色值变化"""
        self._vmin = value
        # 更新HistogramLUTWidget显示范围（单向控制）
        if hasattr(self, 'histogram_widget'):
            self.histogram_widget.setLevels(self._vmin, self._vmax)
        self._update_display_v2()
        self.parametersChanged.emit()

    def _on_vmax_changed_v2(self, value: float):
        """处理最大颜色值变化"""
        self._vmax = value
        # 更新HistogramLUTWidget显示范围（单向控制）
        if hasattr(self, 'histogram_widget'):
            self.histogram_widget.setLevels(self._vmin, self._vmax)
        self._update_display_v2()
        self.parametersChanged.emit()

    def _reset_to_defaults_v2(self):
        """重置为默认值"""
        self._window_frames = 5
        self._distance_start = 40
        self._distance_end = 100
        self._time_downsample = 50
        self._space_downsample = 2
        self._colormap = "jet"
        self._vmin = -0.1
        self._vmax = 0.1

        # 更新UI控件
        self.window_frames_spin.setValue(self._window_frames)
        self.distance_start_spin.setValue(self._distance_start)
        self.distance_end_spin.setValue(self._distance_end)
        self.time_downsample_spin.setValue(self._time_downsample)
        self.space_downsample_spin.setValue(self._space_downsample)
        self.colormap_combo.setCurrentText("Jet")
        self.vmin_spin.setValue(self._vmin)
        self.vmax_spin.setValue(self._vmax)

        # 清空缓冲区
        if self._data_buffer is not None:
            self._data_buffer = deque(maxlen=self._window_frames)

        self.parametersChanged.emit()

    # ========== V2版本的接口兼容性方法 ==========

    def get_parameters(self):
        """获取当前参数 - 兼容原接口"""
        return {
            'window_frames': self._window_frames,
            'distance_range_start': self._distance_start,
            'distance_range_end': self._distance_end,
            'time_downsample': self._time_downsample,
            'space_downsample': self._space_downsample,
            'colormap_type': self._colormap,
            'vmin': self._vmin,
            'vmax': self._vmax
        }

    def set_parameters(self, params):
        """设置参数 - 兼容原接口"""
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
        if 'colormap_type' in params:
            for name, value in COLORMAP_OPTIONS:
                if value == params['colormap_type']:
                    self.colormap_combo.setCurrentText(name)
                    break
        if 'vmin' in params:
            self.vmin_spin.setValue(params['vmin'])
        if 'vmax' in params:
            self.vmax_spin.setValue(params['vmax'])

    def update_data(self, data: np.ndarray) -> bool:
        """数据更新接口 - 兼容原接口"""
        return self.update_data_v2(data)

    def clear_data(self):
        """清空数据接口 - 兼容原接口"""
        if self._data_buffer is not None:
            self._data_buffer.clear()

        # 重置到空显示
        empty_data = np.zeros((10, 10))
        self.image_item.setImage(empty_data, levels=[self._vmin, self._vmax])
        self._current_frame_count = 0
        log.debug("TimeSpacePlotWidgetV2 data cleared")


def create_time_space_widget():
    """
    Create TimeSpace widget instance.

    Returns:
        TimeSpacePlotWidget: A time-space plot widget instance
    """
    log.info("Creating TimeSpacePlotWidget instance")
    return TimeSpacePlotWidgetV2()


# Module exports
__all__ = ['TimeSpacePlotWidget', 'create_time_space_widget']