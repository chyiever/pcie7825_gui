"""
图表交互功能说明文档
Interactive Plot Features Documentation

为三幅图添加了完整的交互功能，包括鼠标操作、坐标显示、缩放等。

功能特性：
"""

# ================================
# 1. 鼠标交互功能
# ================================

"""
鼠标操作支持：

1. 左键拖拽矩形框放大 (Box Zoom)：
   - 按住左键拖拽选择区域
   - 释放后自动放大到选中区域
   - 默认模式为矩形缩放模式

2. 右键拖拽平移 (Pan)：
   - 按住右键拖拽平移视图
   - 可以在放大后移动查看不同区域

3. 滚轮缩放：
   - 鼠标滚轮向上：放大
   - 鼠标滚轮向下：缩小
   - 以鼠标位置为中心缩放

4. 右键菜单：
   - Auto Range：自动调整到最佳显示范围
   - Reset Zoom：重置缩放到初始状态
   - Box Zoom Mode：切换到矩形缩放模式
   - Pan Mode：切换到平移模式
   - Toggle Grid：开启/关闭网格显示
   - Export：导出图片到文件
"""

# ================================
# 2. 实时坐标显示
# ================================

"""
坐标显示功能：

1. 十字光标：
   - 红色虚线十字光标跟随鼠标
   - 实时显示当前鼠标位置
   - 鼠标移出图表区域时自动隐藏

2. 坐标数值显示：
   - 状态栏底部显示三个图表的坐标
   - 格式：图表名: X=数值, Y=数值
   - 根据数据类型自动调整精度：
     * 时域图：整数显示（大值）或3位小数（小值）
     * 频谱图：频率3位小数，幅度1位小数
     * 监控图：同时域图

3. 特殊处理：
   - 频谱图对数坐标：显示实际频率值
   - 超出范围时显示：X=-, Y=-
   - 实时更新，无延迟
"""

# ================================
# 3. 缩放和导航功能
# ================================

"""
缩放控制：

1. 自动范围模式：
   - 初始化时自动调整到数据范围
   - 可通过右键菜单重新启用

2. 手动缩放模式：
   - 支持独立的X轴和Y轴缩放
   - 缩放后保持用户设置
   - 不会自动重置范围

3. 重置功能：
   - Auto Range：回到数据的最佳显示范围
   - Reset Zoom：重置到初始缩放状态

4. 平移功能：
   - 放大后可以平移查看不同区域
   - 支持拖拽平移和键盘导航
"""

# ================================
# 4. 导出功能
# ================================

"""
图片导出：

支持格式：
- PNG：高质量位图格式
- SVG：矢量图格式（可无损缩放）

导出步骤：
1. 右键点击要导出的图表
2. 选择"Export [图表名]..."
3. 选择保存位置和文件格式
4. 状态栏显示导出结果

文件命名：
- 默认名称基于图表类型
- time_domain.png, spectrum.png, monitor.png
"""

# ================================
# 5. 技术实现细节
# ================================

"""
核心技术：

1. pyqtgraph.InfiniteLine：
   - 实现十字光标显示
   - 红色虚线样式，不影响数据边界

2. ViewBox交互模式：
   - RectMode：矩形缩放模式
   - PanMode：平移模式
   - 可动态切换

3. 鼠标事件处理：
   - sigMouseMoved：鼠标移动事件
   - 场景坐标到数据坐标的转换
   - 异常处理确保稳定性

4. 上下文菜单：
   - QMenu自定义菜单项
   - Lambda表达式连接信号槽
   - 动态功能切换

5. 坐标转换：
   - mapSceneToView()：场景坐标到视图坐标
   - 处理对数坐标的特殊情况
   - 格式化显示精度控制
"""

# ================================
# 6. 使用指南
# ================================

"""
常用操作指南：

1. 查看数据细节：
   - 移动鼠标查看坐标值
   - 左键拖拽矩形放大感兴趣区域
   - 滚轮进一步微调缩放

2. 导航和重置：
   - 右键拖拽平移到其他区域
   - 右键菜单"Auto Range"快速重置
   - 使用滚轮以鼠标位置为中心缩放

3. 模式切换：
   - 右键菜单切换"Box Zoom"和"Pan Mode"
   - Box Zoom：适合选择区域放大
   - Pan Mode：适合浏览已放大的数据

4. 数据导出：
   - 调整到想要的显示效果
   - 右键菜单选择导出
   - 选择合适的文件格式保存

5. 网格控制：
   - 右键菜单"Toggle Grid"开关网格
   - 网格有助于读取精确数值

性能优化：
- 交互响应快速，不影响数据采集
- 坐标显示采用异常保护，确保稳定
- 十字光标仅在需要时显示，减少绘图负荷
"""

# ================================
# 7. 代码结构说明
# ================================

"""
主要函数：

1. _setup_plot_interactions()：
   - 初始化所有交互功能
   - 设置鼠标模式和菜单

2. _update_crosshair()：
   - 更新十字光标位置
   - 更新坐标显示标签
   - 处理不同图表类型的坐标格式

3. _create_plot_context_menu()：
   - 创建右键上下文菜单
   - 添加各种功能选项

4. _toggle_grid()：
   - 切换网格显示状态

5. _export_plot()：
   - 处理图表导出功能

UI组件：
- coord_label_1/2/3：坐标显示标签
- vLine/hLine：十字光标线条
- 自定义右键菜单

事件连接：
- sigMouseMoved：鼠标移动事件
- 菜单项clicked事件
- 键盘快捷键（可扩展）
"""

# ================================
# 8. 扩展建议
# ================================

"""
可进一步扩展的功能：

1. 数据测量工具：
   - 添加标尺工具测量距离
   - 峰值检测和标记
   - 数据点标注功能

2. 多光标支持：
   - 添加可移动的测量光标
   - 显示两点间的差值
   - 频率和幅度的精确测量

3. 数据分析工具：
   - 统计信息显示（最大值、最小值、平均值）
   - 区域数据导出
   - 简单的数学运算（平滑、滤波等）

4. 显示优化：
   - 数据点密度自适应
   - 多层次细节显示
   - 数据抽取算法优化

5. 快捷键支持：
   - 键盘快捷键定义
   - 快速缩放和重置
   - 模式切换快捷键

这些交互功能大大提升了数据分析的便利性和效率。
"""

if __name__ == "__main__":
    print("图表交互功能说明文档")
    print("详细功能说明请参考以上注释")

# 使用示例代码
def demo_usage():
    """
    示例：如何在其他项目中使用类似的交互功能
    """

    # 1. 创建基本绘图
    import pyqtgraph as pg
    from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
    from PyQt5.QtCore import Qt

    app = QApplication([])

    # 创建窗口和布局
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # 创建绘图控件
    plot_widget = pg.PlotWidget()
    layout.addWidget(plot_widget)

    # 2. 添加交互功能
    # 启用鼠标交互
    plot_widget.setMenuEnabled(True)
    plot_widget.getViewBox().setMouseEnabled(x=True, y=True)

    # 添加十字光标
    vLine = pg.InfiniteLine(angle=90, movable=False,
                           pen=pg.mkPen('r', width=1, style=Qt.DashLine))
    hLine = pg.InfiniteLine(angle=0, movable=False,
                           pen=pg.mkPen('r', width=1, style=Qt.DashLine))
    plot_widget.addItem(vLine, ignoreBounds=True)
    plot_widget.addItem(hLine, ignoreBounds=True)

    # 连接鼠标事件
    def update_crosshair(pos):
        if plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = plot_widget.getViewBox().mapSceneToView(pos)
            x, y = mouse_point.x(), mouse_point.y()
            vLine.setPos(x)
            hLine.setPos(y)
            print(f"Mouse: X={x:.3f}, Y={y:.3f}")

    plot_widget.scene().sigMouseMoved.connect(update_crosshair)

    # 3. 添加测试数据
    import numpy as np
    x = np.linspace(0, 10, 1000)
    y = np.sin(x) + 0.1 * np.random.randn(1000)
    plot_widget.plot(x, y, pen='b')

    # 显示窗口
    widget.show()
    widget.resize(800, 600)

    # 运行应用
    # app.exec_()  # 取消注释以运行演示

    print("交互功能演示代码已准备就绪")

if __name__ == "__main__":
    demo_usage()