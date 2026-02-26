# DAS GUI Time-Space Plot综合开发文档

**文档版本**: v1.3.0
**修改日期**: 2026-02-25
**开发团队**: Claude & QGH
**涵盖内容**: 坐标轴刻度修复、Time-Space绘制技术选型、颜色栏优化、运行时模式切换修复

---

## 1. Time-Space绘制技术架构选择

### 1.1 技术方案对比

#### 方案A: ImageView组件（原有实现）
```python
# 核心实现
self.image_view = pg.ImageView()
self.image_view.setImage(data, autoRange=False, autoLevels=False)
```

**优势**:
- 内置ColorBar，UI完整性好
- GPU硬件加速支持，性能优秀
- API简洁，开发效率高

**限制**:
- 坐标轴刻度控制困难，PyQtGraph版本兼容性差
- 内部PlotItem访问路径不稳定：`getView().getPlotItem()` vs `getView()`
- 轴配置受ImageView内部封装限制

#### 方案B: PlotWidget + ImageItem（技术升级）
```python
# 推荐架构
self.plot_widget = pg.PlotWidget()
self.image_item = pg.ImageItem()
self.plot_widget.addItem(self.image_item)

# 完整轴控制
self.plot_widget.setLabel('bottom', 'Distance (points)')
self.plot_widget.setLabel('left', 'Time (samples)')
```

**技术优势**:
- 完整的坐标轴控制权限
- 跨PyQtGraph版本兼容性好
- 自定义ColorBar集成度高

**实施成本**:
- 需重构现有数据更新逻辑
- 手动ColorBar开发工作量

### 1.2 最终技术选择

**当前**: 继续使用ImageView + 增强型坐标配置
**原因**:
1. 核心功能满足用户需求，投入产出比高
2. 避免大幅度架构变更风险
3. 通过坐标映射技术解决关键问题

---

## 2. 坐标轴刻度显示技术突破

### 2.1 问题根因分析

#### PyQtGraph版本兼容性挑战
```python
# 不同版本API差异
# v0.11.x: ImageView.getView().getPlotItem()
# v0.12.x: ImageView.getView() 直接返回PlotItem
# v0.13.x: 内部结构重组
```

#### 鲁棒获取PlotItem方案
```python
def _get_plot_item_robust(self):
    """跨版本PlotItem获取"""
    try:
        view = self.image_view.getView()
        if hasattr(view, 'showAxis'):
            return view  # 新版本直接返回
        elif hasattr(view, 'getPlotItem'):
            return view.getPlotItem()  # 旧版本需要调用

        # 备用路径：通过UI访问
        if hasattr(self.image_view, 'ui'):
            return self.image_view.ui.graphicsView.getPlotItem()
    except Exception as e:
        log.warning(f"PlotItem获取失败: {e}")
    return None
```

### 2.2 坐标映射技术突破

#### 核心修复: setRect坐标映射
```python
# 关键技术：将像素坐标映射到物理坐标
rect = QtCore.QRectF(0, distance_start_actual, time_duration_s,
                   distance_end_actual - distance_start_actual)
image_item.setRect(rect)
```

**技术原理**:
- X轴: [0, time_duration_s] 秒
- Y轴: [distance_start, distance_end] 点数
- 解决Y轴起始点从0开始的问题

#### 视图范围强制控制
```python
view.setRange(xRange=[0, time_duration_s],
              yRange=[distance_start_actual, distance_end_actual],
              padding=0)
view.enableAutoRange(enable=False)
```

**核心价值**: 禁用自动范围，确保坐标轴紧贴真实数据范围

### 2.3 时间轴独立性修复

#### 问题: Time DS影响X轴范围
```python
# 错误实现：时间受降采样影响
time_duration = downsampled_frames / scan_rate  # ❌

# 正确实现：时间基于原始帧数
time_duration_s = original_time_points / scan_rate_hz  # ✅
```

**技术意义**: X轴时间范围保持物理意义正确性，不受界面参数影响

---

## 3. 颜色栏功能增强

### 3.1 技术升级: HistogramLUTWidget

#### 原有ColorBar问题
- 功能单一，仅显示颜色映射
- 缺少数据分布可视化
- 交互性限制，调整不直观

#### HistogramLUTWidget技术优势
```python
# 专业科学可视化颜色控制
self.histogram_widget = pg.HistogramLUTWidget()
self.histogram_widget.setImageItem(self.image_item)

# 布局集成
layout.addWidget(self.image_view, 0, 0)
layout.addWidget(self.histogram_widget, 0, 1)  # 右侧显示
```

**功能提升**:
- 垂直颜色渐变条（修复方向问题）
- 实时直方图分布显示
- 交互式亮度/对比度调整
- 颜色映射实时同步

### 3.2 颜色范围优化
```python
# 针对相位数据优化默认范围
vmin: float = -0.1    # -1000.0 → -0.1
vmax: float = 0.1     # 1000.0 → 0.1
```

---

## 4. 运行时模式切换稳定性修复

### 4.1 问题根因: 方法调用错误
```python
# 崩溃原因
AttributeError: 'MainWindow' object has no attribute '_update_params'
```

### 4.2 安全参数更新策略

#### 原有错误实现
```python
def _on_mode_changed(self, checked):
    self._update_params()  # ❌ 方法不存在，导致崩溃
```

#### 安全修复方案
```python
@pyqtSlot(bool)
def _on_mode_changed(self, checked):
    """安全的运行时模式切换"""
    if checked:
        try:
            if hasattr(self, 'params') and self.params is not None:
                # 只更新必要的显示模式参数
                if self.mode_space_radio.isChecked():
                    self.params.display.mode = DisplayMode.SPACE
                else:
                    self.params.display.mode = DisplayMode.TIME

                self.params.display.region_index = self.region_index_spin.value()
                log.debug(f"Mode changed to: {self.params.display.mode}")
        except Exception as e:
            log.warning(f"Mode update error: {e}")
```

**技术亮点**:
- 避免运行时调用`_collect_params()`（可能访问不稳定组件）
- 只更新必要参数，保持系统稳定性
- 完善异常处理，防止单点故障

### 4.3 信号连接完善
```python
# 新增运行时信号连接
self.mode_time_radio.toggled.connect(self._on_mode_changed)
self.mode_space_radio.toggled.connect(self._on_mode_changed)
self.region_index_spin.valueChanged.connect(self._on_region_changed)
```

---

## 5. Tab独立性设计

### 5.1 问题: Tab间数据更新干扰
```python
# 原有问题：无论哪个Tab活动都更新Time-Space图
if time_space_widget.is_plot_enabled():
    update_time_space_plot()  # ❌ 导致Tab1/Tab2相互干扰
```

### 5.2 解决方案: 活动Tab检查
```python
# 修复：只有Tab2活动时才更新
if (self.time_space_widget is not None and
    hasattr(self.time_space_widget, 'is_plot_enabled') and
    self.time_space_widget.is_plot_enabled() and
    self.plot_tabs.currentIndex() == 1):  # 关键：Tab2活动检查
    update_time_space_plot()
```

**技术价值**: 确保Tab1（Time Plot）和Tab2（Time-Space Plot）独立工作

---

## 6. MODE控制重构

### 6.1 界面控制优化

#### 原有问题: MODE选项混乱
- Tab1中包含"Time-space"选项，逻辑混乱
- 用户需在两个地方控制Time-space功能

#### 重构方案: PLOT按钮控制
```python
# Tab2中添加PLOT按钮
self.plot_btn = QPushButton("PLOT")
self.plot_btn.setCheckable(True)
self.plot_btn.clicked.connect(self._on_plot_clicked)

# 移除Tab1中的Time-space选项
# Tab1只保留Time/Space两种模式
```

**用户体验提升**:
- 功能集中化：Time-space功能完全在Tab2控制
- 交互直观化：PLOT按钮状态直接对应功能开关
- 逻辑清晰化：避免跨Tab的功能依赖

---

## 7. 默认参数优化

### 7.1 基于用户习惯的默认值调整
```python
# 相位解调参数优化
self.detrend_bw_spin.setValue(10.0)      # 0.5Hz → 10Hz
self.polar_div_check.setChecked(True)    # False → True

# Time-Space参数优化
distance_range_start: int = 40           # 更实用的范围
distance_range_end: int = 100
vmin: float = -0.1                       # 适合相位数据
vmax: float = 0.1
rad_enable: bool = True                  # 默认启用rad转换
```

---

## 8. 核心技术成果总结

### 8.1 成功解决的关键问题
1. **✅ Y轴起始点修复**: 通过setRect()实现从distance_start开始显示
2. **✅ 时间轴独立性**: X轴范围不受Time DS参数影响
3. **✅ 运行时模式切换**: 修复崩溃，支持无重启参数切换
4. **✅ 颜色栏功能增强**: HistogramLUTWidget提供专业可视化控制
5. **✅ Tab独立性**: 确保Tab1/Tab2数据更新不互相干扰

### 8.2 技术架构价值
- **稳定性优先**: 在保持兼容性前提下渐进式改进
- **用户体验**: 默认值优化、界面逻辑简化、实时参数应用
- **可维护性**: 模块化设计、完善异常处理、详细日志记录

### 8.3 工程经验
1. **PyQtGraph复杂性**: ImageView坐标控制需要版本兼容性考虑
2. **用户反馈重要性**: 实际运行效果是最终验证标准
3. **渐进式开发**: 分步验证，避免大幅架构变更风险

---

## 9. 代码变更统计

```
src/time_space_plot.py:
  + HistogramLUTWidget集成 (~40行)
  + PLOT按钮控制逻辑 (~30行)
  + 坐标映射setRect实现 (~20行)
  + 时间计算独立性修复 (~15行)

src/main_window.py:
  + 运行时模式切换修复 (~25行)
  + Tab独立性检查逻辑 (~10行)
  + 信号连接完善 (~8行)
  + 默认参数值优化 (~5行)

总计: ~150行核心功能代码
```

---

**开发完成标志**: ✅ **Time-Space Plot模块全面优化完成**

**技术价值**: 在确保系统稳定的基础上，实现了坐标精度、用户交互、可视化效果的显著提升，为DAS GUI提供了专业级的时空域分析能力。