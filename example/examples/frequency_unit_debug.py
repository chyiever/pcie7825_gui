"""
单位显示问题调试
"""

# 相位数据频谱显示单位问题分析

"""
问题描述：
相位数据功率谱和PSD的横轴单位应该是Hz，但显示的是kHz

原因分析：
1. 相位数据采样率：scan_rate = 2000 Hz (正确)
2. 频谱计算：最大频率 = 2000/2 = 1000 Hz (正确)
3. 单位显示：pyqtgraph可能自动将大于1000的Hz转换为kHz显示

解决方案：
在setLabel时明确指定单位，避免pyqtgraph的自动单位转换
"""

def analyze_frequency_range():
    """分析频率范围和单位显示"""

    # 相位数据参数
    scan_rate = 2000  # Hz
    nyquist = scan_rate / 2  # 1000 Hz

    print(f"扫描率: {scan_rate} Hz")
    print(f"奈奎斯特频率: {nyquist} Hz")
    print(f"频谱范围: 0 - {nyquist} Hz")

    # 检查是否超过kHz阈值
    if nyquist >= 1000:
        print(f"注意：频率超过1000Hz，pyqtgraph可能自动显示为kHz")
        print(f"应该显示: 0 - {nyquist} Hz")
        print(f"可能显示: 0 - {nyquist/1000:.1f} kHz")

    return nyquist

if __name__ == "__main__":
    analyze_frequency_range()

"""
修复建议：
1. 在setLabel时不使用units参数，直接在标签文本中包含单位
2. 或者确保传递给pyqtgraph的频率数据保持在Hz范围内
3. 检查pyqtgraph版本是否有自动单位转换功能
"""