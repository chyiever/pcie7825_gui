"""
功率谱和功率谱密度计算详解
Power Spectrum and Power Spectral Density (PSD) Analysis

本文档详细解释了spectrum_analyzer.py中功率谱和PSD的计算原理和实现
"""

import numpy as np
import matplotlib.pyplot as plt


class SpectrumEducational:
    """
    教育版频谱分析器，用于演示功率谱和PSD的计算过程
    """

    def __init__(self):
        self.IMPEDANCE = 50.0  # 参考阻抗 (Ohms)

    def demo_power_spectrum_calculation(self, data, sample_rate, psd_mode=False):
        """
        演示功率谱计算的详细步骤

        Args:
            data: 时域数据
            sample_rate: 采样率 (Hz)
            psd_mode: True=计算PSD, False=计算功率谱
        """
        print("=" * 60)
        print(f"功率谱计算演示 (PSD模式: {psd_mode})")
        print("=" * 60)

        # 步骤1: 数据预处理
        print("\n步骤1: 数据预处理")
        print(f"原始数据长度: {len(data)}")
        print(f"采样率: {sample_rate} Hz")

        # 如果是int16数据，转换为电压值
        if data.dtype == np.int16:
            # 假设16位ADC，满量程0.95V
            data_v = data.astype(np.float64) * 0.95 / 32767.0
            print(f"数据类型: int16 → 转换为电压值 (范围: ±0.95V)")
        else:
            # 相位数据或其他
            data_v = data.astype(np.float64)
            print(f"数据类型: {data.dtype} → 直接使用")

        n = len(data_v)
        print(f"处理后数据长度: {n}")

        # 步骤2: 加窗
        print("\n步骤2: 加窗处理")
        window = np.hanning(n)
        windowed_data = data_v * window

        # 窗函数校正因子
        coherent_gain = np.sum(window) / n  # 相干增益
        noise_bandwidth = np.sum(window**2) / (np.sum(window)**2) * n  # 噪声带宽

        print(f"窗函数类型: Hanning")
        print(f"相干增益: {coherent_gain:.6f}")
        print(f"噪声带宽: {noise_bandwidth:.6f}")

        # 步骤3: FFT
        print("\n步骤3: FFT变换")
        fft_result = np.fft.fft(windowed_data)
        print(f"FFT长度: {len(fft_result)}")

        # 步骤4: 计算功率谱
        print("\n步骤4: 计算功率谱")
        n_half = n // 2

        # 计算双边功率谱
        power_spectrum_double = np.abs(fft_result)**2 / (n**2)

        # 转换为单边功率谱（只取正频率部分）
        power_spectrum = power_spectrum_double[:n_half]

        # 校正相干增益
        power_spectrum /= coherent_gain**2

        # 除DC外，其他频率成分乘以2（因为去掉了负频率）
        power_spectrum[1:] *= 2

        print(f"单边功率谱长度: {len(power_spectrum)}")
        print(f"功率谱单位: V²")

        # 步骤5: 频率轴
        print("\n步骤5: 创建频率轴")
        df = sample_rate / n  # 频率分辨率
        freq_axis = np.arange(n_half) * df
        print(f"频率分辨率: {df:.3f} Hz")
        print(f"频率范围: 0 - {freq_axis[-1]:.1f} Hz")

        # 步骤6: 转换为dB
        print("\n步骤6: 转换为dB")

        if psd_mode:
            print("计算功率谱密度 (PSD):")
            # PSD: 功率谱除以频率分辨率，并校正窗函数噪声带宽
            power_density = power_spectrum / (df * noise_bandwidth)
            spectrum_db = 10.0 * np.log10(power_density + 1e-20)
            print(f"  - 除以频率分辨率: {df:.3f} Hz")
            print(f"  - 除以噪声带宽: {noise_bandwidth:.6f}")
            print(f"  - 单位: dB/Hz")
            unit_str = "dB/Hz"
        else:
            print("计算功率谱:")
            spectrum_db = 10.0 * np.log10(power_spectrum + 1e-20)
            print(f"  - 直接转换为dB")
            print(f"  - 单位: dB")
            unit_str = "dB"

        print(f"最终频谱范围: {np.min(spectrum_db):.1f} - {np.max(spectrum_db):.1f} {unit_str}")

        return freq_axis, spectrum_db, df

    def compare_power_vs_psd(self, data, sample_rate):
        """
        比较功率谱和PSD的区别
        """
        print("\n" + "=" * 60)
        print("功率谱 vs PSD 比较")
        print("=" * 60)

        # 计算功率谱
        freq1, power_spectrum, df1 = self.demo_power_spectrum_calculation(
            data, sample_rate, psd_mode=False
        )

        # 计算PSD
        freq2, psd_spectrum, df2 = self.demo_power_spectrum_calculation(
            data, sample_rate, psd_mode=True
        )

        print("\n关键区别:")
        print("1. 功率谱 (Power Spectrum):")
        print("   - 单位: dB")
        print("   - 物理意义: 各频率成分的功率大小")
        print("   - 与数据长度和采样率有关")

        print("\n2. 功率谱密度 (PSD):")
        print("   - 单位: dB/Hz")
        print("   - 物理意义: 单位频率带宽内的功率")
        print("   - 归一化了频率分辨率，便于不同参数数据比较")
        print("   - PSD = 功率谱 / (频率分辨率 × 窗函数噪声带宽)")

        return freq1, power_spectrum, freq2, psd_spectrum

    def demonstrate_windowing_effects(self, n_samples=1024):
        """
        演示不同窗函数的效果
        """
        print("\n" + "=" * 60)
        print("窗函数效果演示")
        print("=" * 60)

        # 创建测试信号：两个正弦波
        sample_rate = 1000  # 1kHz采样率
        t = np.arange(n_samples) / sample_rate
        freq1, freq2 = 100, 150  # 两个频率成分
        signal = np.sin(2*np.pi*freq1*t) + 0.5*np.sin(2*np.pi*freq2*t)

        # 不同窗函数
        windows = {
            'Rectangular': np.ones(n_samples),
            'Hanning': np.hanning(n_samples),
            'Hamming': np.hamming(n_samples),
            'Blackman': np.blackman(n_samples)
        }

        print(f"测试信号: {freq1}Hz + {freq2}Hz (幅度比2:1)")
        print(f"采样率: {sample_rate}Hz, 样本数: {n_samples}")

        for window_name, window in windows.items():
            # 计算窗函数参数
            coherent_gain = np.sum(window) / n_samples
            noise_bandwidth = np.sum(window**2) / (np.sum(window)**2) * n_samples

            print(f"\n{window_name}窗:")
            print(f"  相干增益: {coherent_gain:.6f}")
            print(f"  噪声带宽: {noise_bandwidth:.6f}")
            print(f"  频率分辨率: {sample_rate/n_samples:.2f} Hz")


def main_demo():
    """
    主演示函数
    """
    print("功率谱和PSD计算教学演示")
    print("=" * 60)

    # 创建教学用分析器
    analyzer = SpectrumEducational()

    # 生成测试数据
    sample_rate = 1000  # 1kHz
    duration = 1.0      # 1秒
    n_samples = int(sample_rate * duration)

    t = np.linspace(0, duration, n_samples, endpoint=False)

    # 测试信号：100Hz正弦波 + 噪声
    frequency = 100  # Hz
    amplitude = 1.0
    noise_level = 0.1

    signal = amplitude * np.sin(2 * np.pi * frequency * t) + \
             noise_level * np.random.randn(n_samples)

    print(f"测试信号参数:")
    print(f"  频率: {frequency} Hz")
    print(f"  幅度: {amplitude}")
    print(f"  噪声水平: {noise_level}")
    print(f"  采样率: {sample_rate} Hz")
    print(f"  数据长度: {n_samples}")

    # 转换为int16格式模拟ADC数据
    signal_int16 = (signal * 32767 / max(abs(signal))).astype(np.int16)

    # 演示计算过程
    freq_power, power_db, _ = analyzer.demo_power_spectrum_calculation(
        signal_int16, sample_rate, psd_mode=False
    )

    freq_psd, psd_db, _ = analyzer.demo_power_spectrum_calculation(
        signal_int16, sample_rate, psd_mode=True
    )

    # 比较结果
    analyzer.compare_power_vs_psd(signal_int16, sample_rate)

    # 窗函数演示
    analyzer.demonstrate_windowing_effects()

    print("\n" + "=" * 60)
    print("核心公式总结:")
    print("=" * 60)
    print("1. FFT: X(k) = Σ x(n) * w(n) * e^(-j2πkn/N)")
    print("2. 功率谱: P(k) = |X(k)|² / (N² * coherent_gain²)")
    print("3. 单边谱: P_single(k) = 2 * P(k)  (k > 0)")
    print("4. PSD: PSD(k) = P_single(k) / (Δf * noise_bandwidth)")
    print("5. dB转换: dB = 10 * log10(P + ε)")
    print("\n其中:")
    print("  N = 数据长度")
    print("  w(n) = 窗函数")
    print("  coherent_gain = Σw(n) / N")
    print("  noise_bandwidth = N * Σw(n)² / (Σw(n))²")
    print("  Δf = 采样率 / N")


if __name__ == "__main__":
    main_demo()


"""
关键概念解释:

1. 功率谱 (Power Spectrum):
   - 测量信号中各频率成分的功率大小
   - 单位通常为dB或V²
   - 受数据长度和采样参数影响

2. 功率谱密度 (PSD):
   - 表示单位频率带宽内的功率
   - 单位为dB/Hz或V²/Hz
   - 归一化了频率分辨率，便于比较不同长度的数据

3. 为什么要用PSD:
   - 当比较不同长度或不同采样率的数据时，PSD更有意义
   - PSD消除了频率分辨率的影响
   - 更适合噪声和随机信号的分析

4. 窗函数的作用:
   - 减少频谱泄漏 (spectral leakage)
   - 改善频率分辨率
   - 需要校正相干增益和噪声带宽

5. 实际应用中的注意事项:
   - 选择合适的窗函数（Hanning常用于一般分析）
   - 注意频率分辨率 = 采样率 / 数据长度
   - 考虑信噪比对结果的影响
"""