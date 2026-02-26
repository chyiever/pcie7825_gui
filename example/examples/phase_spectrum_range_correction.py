"""
相位数据频谱X轴范围修正说明
Phase Data Spectrum X-axis Range Correction

修改目的：
绘制相位的功率谱或PSD时，X轴范围设置为(1, fs/2)而不是(0, fs/2)

技术背景：
"""

# ================================
# 为什么要从1Hz开始？
# ================================

"""
物理原理：
1. DC成分（0Hz）对于相位数据通常没有物理意义
2. 相位测量中，0Hz附近的低频成分可能包含系统噪声
3. 分布式光纤传感关注的是振动信号，通常在1Hz以上
4. 排除0Hz可以避免DC偏移对频谱分析的影响

数学考虑：
1. 功率谱密度(PSD)在0Hz附近可能有奇异值
2. 对数运算时避免log(0)的问题
3. 频谱分析的有效范围通常从1Hz开始
"""

# ================================
# 修改内容详解
# ================================

"""
修改前：
```python
# 所有数据类型都从0Hz开始
valid_indices = (freq >= 0) & (freq <= nyquist)
```

修改后：
```python
if data_type == 'int':  # 相位数据
    # 相位数据：X轴范围[1, fs/2]，排除0Hz和DC成分
    valid_indices = (freq >= 1.0) & (freq <= nyquist)
else:  # 原始数据
    # 原始数据：从0Hz开始
    valid_indices = (freq >= 0) & (freq <= nyquist)
```

X轴范围设置：
```python
if data_type == 'int':  # 相位数据
    # 相位数据：显式设置X轴范围[1, fs/2]
    self.plot_widget_2.setXRange(1.0, nyquist_display, padding=0.02)
else:  # 原始数据
    # 原始数据：自动范围（从0开始）
    self.plot_widget_2.enableAutoRange(axis='x')
```
"""

# ================================
# 实际效果
# ================================

"""
参数示例：
- 扫描率(scan_rate) = 2000 Hz
- 奈奎斯特频率 = 1000 Hz

修改前的显示范围：
- 相位数据频谱：X轴 0 - 1000 Hz
- 原始数据频谱：X轴 0 - 500 MHz

修改后的显示范围：
- 相位数据频谱：X轴 1 - 1000 Hz  ✓（排除了0Hz）
- 原始数据频谱：X轴 0 - 500 MHz  （保持不变）

显示改进：
1. 相位数据不再显示0Hz的DC成分
2. 频谱分析更聚焦于有意义的频率范围
3. 避免了0Hz附近的噪声干扰
4. 符合振动监测的实际需求
"""

# ================================
# 代码逻辑说明
# ================================

"""
数据处理流程：

1. 频谱计算：
   ```python
   freq, spectrum, df = self.spectrum_analyzer.update(data, sample_rate, psd_mode, data_type)
   ```
   - 返回完整的频谱数据（包含0Hz）

2. 频率过滤：
   ```python
   if data_type == 'int':  # 相位数据
       valid_indices = (freq >= 1.0) & (freq <= nyquist)
   else:  # 原始数据
       valid_indices = (freq >= 0) & (freq <= nyquist)
   ```
   - 相位数据：过滤掉<1Hz的成分
   - 原始数据：保留从0Hz开始

3. X轴范围设置：
   ```python
   if data_type == 'int':
       self.plot_widget_2.setXRange(1.0, nyquist_display, padding=0.02)
   ```
   - 明确设置显示范围
   - padding=0.02 提供2%的边距

4. 显示更新：
   ```python
   self.spectrum_curve.setData(freq_display, spectrum_filtered)
   ```
   - 只显示过滤后的有效频率范围
"""

# ================================
# 优势分析
# ================================

"""
技术优势：
1. 物理意义更清晰：专注于振动信号的有效频率范围
2. 视觉效果更好：避免0Hz的大幅值压缩其他频率的显示
3. 数据分析更准确：排除DC成分的干扰
4. 符合行业标准：振动分析通常从1Hz开始

实际应用：
1. 分布式光纤传感系统主要检测1Hz以上的振动
2. 0Hz的DC成分通常是系统偏移，不是感兴趣的信号
3. 频谱分析更聚焦于有用的信号成分
4. 便于识别和分析具体的振动频率
"""

# ================================
# 测试验证
# ================================

"""
测试要点：

1. 相位数据频谱：
   - X轴最小值应该是1Hz，不是0Hz
   - X轴最大值应该是fs/2 (如1000Hz)
   - 频谱曲线应该从1Hz开始显示
   - 标签显示"Frequency (Hz)"

2. 原始数据频谱：
   - X轴最小值仍然是0MHz（保持原样）
   - X轴最大值是fs/2转换的MHz值
   - 行为与之前一致

3. 显示范围：
   - 相位数据图表自动聚焦到[1, fs/2]范围
   - padding=0.02提供适当的边距
   - 不需要手动调整范围

预期结果：
- 相位数据的功率谱和PSD更聚焦于有意义的频率范围
- 排除了0Hz的DC成分干扰
- 更符合振动监测的实际应用需求
"""

def calculate_phase_spectrum_range(scan_rate=2000):
    """计算相位数据频谱的显示范围"""
    nyquist = scan_rate / 2
    min_freq = 1.0  # Hz
    max_freq = nyquist  # Hz

    print(f"扫描率: {scan_rate} Hz")
    print(f"奈奎斯特频率: {nyquist} Hz")
    print(f"相位数据频谱显示范围: {min_freq} - {max_freq} Hz")
    print(f"排除的DC成分: 0 - {min_freq} Hz")

    return min_freq, max_freq

if __name__ == "__main__":
    print("相位数据频谱X轴范围修正说明")
    print("="*50)
    calculate_phase_spectrum_range()
    print("\n修改要点：")
    print("1. 相位数据频谱从1Hz开始，排除DC成分")
    print("2. 原始数据频谱保持从0开始不变")
    print("3. 显示范围自动设置为[1, fs/2]")
    print("4. 更符合振动监测的实际需求")