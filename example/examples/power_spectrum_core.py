"""
功率谱和PSD核心计算代码
基于 spectrum_analyzer.py 的核心算法提取
"""

import numpy as np
from typing import Tuple


def calculate_power_spectrum_and_psd(data: np.ndarray,
                                   sample_rate: float,
                                   psd_mode: bool = False) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    计算功率谱或功率谱密度的核心函数

    Args:
        data: 时域输入数据
        sample_rate: 采样率 (Hz)
        psd_mode: True=计算PSD, False=计算功率谱

    Returns:
        (频率轴, 频谱dB值, 频率分辨率)
    """

    # ========== 步骤1: 数据长度和基本参数 ==========
    n = len(data)
    print(f"数据长度: {n}")
    print(f"采样率: {sample_rate} Hz")

    # ========== 步骤2: 加窗处理 ==========
    # 使用Hanning窗减少频谱泄漏
    window = np.hanning(n)
    windowed_data = data * window

    # 计算窗函数校正因子
    coherent_gain = np.sum(window) / n  # 相干增益校正
    noise_bandwidth = np.sum(window**2) / (np.sum(window)**2) * n  # 噪声带宽校正

    print(f"相干增益: {coherent_gain:.6f}")
    print(f"噪声带宽: {noise_bandwidth:.6f}")

    # ========== 步骤3: FFT变换 ==========
    fft_result = np.fft.fft(windowed_data)
    print(f"FFT完成，长度: {len(fft_result)}")

    # ========== 步骤4: 计算功率谱 ==========
    # 只取正频率部分（单边谱）
    n_half = n // 2

    # 计算功率谱：|X(f)|² / N²
    power_spectrum = np.abs(fft_result[:n_half])**2 / (n**2)

    # 校正窗函数的相干增益
    power_spectrum /= coherent_gain**2

    # 单边谱校正：除DC外其他频率成分乘以2
    power_spectrum[1:] *= 2

    # ========== 步骤5: 频率轴 ==========
    df = sample_rate / n  # 频率分辨率
    freq_axis = np.arange(n_half) * df

    print(f"频率分辨率: {df:.3f} Hz")
    print(f"频率范围: 0 到 {freq_axis[-1]:.1f} Hz")

    # ========== 步骤6: 转换为dB ==========
    if psd_mode:
        print("计算PSD模式...")
        # PSD = 功率谱 / (频率分辨率 × 噪声带宽)
        power_density = power_spectrum / (df * noise_bandwidth)
        spectrum_db = 10.0 * np.log10(power_density + 1e-20)  # +1e-20防止log(0)
        print("单位: dB/Hz")
    else:
        print("计算功率谱模式...")
        # 直接转换为dB
        spectrum_db = 10.0 * np.log10(power_spectrum + 1e-20)
        print("单位: dB")

    print(f"频谱范围: {np.min(spectrum_db):.1f} 到 {np.max(spectrum_db):.1f} dB")

    return freq_axis, spectrum_db, df


def demo_with_test_signal():
    """
    使用测试信号演示计算过程
    """
    print("=" * 70)
    print("功率谱/PSD计算演示")
    print("=" * 70)

    # 创建测试信号：100Hz正弦波 + 200Hz正弦波 + 噪声
    sample_rate = 1000.0  # 1kHz采样率
    duration = 2.0        # 2秒数据
    n_samples = int(sample_rate * duration)

    t = np.linspace(0, duration, n_samples, endpoint=False)

    # 信号成分
    signal = (1.0 * np.sin(2*np.pi*100*t) +     # 100Hz, 幅度1.0
              0.5 * np.sin(2*np.pi*200*t) +     # 200Hz, 幅度0.5
              0.1 * np.random.randn(n_samples)) # 白噪声

    print(f"测试信号: 100Hz(幅度1.0) + 200Hz(幅度0.5) + 白噪声(0.1)")

    # 计算功率谱
    print("\n" + "="*50)
    print("功率谱计算:")
    print("="*50)
    freq1, power_spec, df1 = calculate_power_spectrum_and_psd(signal, sample_rate, psd_mode=False)

    # 计算PSD
    print("\n" + "="*50)
    print("PSD计算:")
    print("="*50)
    freq2, psd_spec, df2 = calculate_power_spectrum_and_psd(signal, sample_rate, psd_mode=True)

    # 找到峰值频率
    print("\n" + "="*50)
    print("结果分析:")
    print("="*50)

    # 功率谱峰值
    power_peaks = find_peaks(freq1, power_spec, threshold=-20)
    print("功率谱峰值频率:")
    for freq, power in power_peaks:
        print(f"  {freq:.1f} Hz: {power:.1f} dB")

    # PSD峰值
    psd_peaks = find_peaks(freq2, psd_spec, threshold=-20)
    print("PSD峰值频率:")
    for freq, power in psd_peaks:
        print(f"  {freq:.1f} Hz: {power:.1f} dB/Hz")

    return freq1, power_spec, freq2, psd_spec


def find_peaks(freq, spectrum, threshold=-10):
    """
    简单的峰值检测
    """
    peaks = []
    # 只看前一半频率范围，避免高频噪声
    max_idx = len(spectrum) // 2

    for i in range(1, max_idx-1):
        if (spectrum[i] > threshold and
            spectrum[i] > spectrum[i-1] and
            spectrum[i] > spectrum[i+1]):
            peaks.append((freq[i], spectrum[i]))

    return sorted(peaks, key=lambda x: x[1], reverse=True)


def compare_different_data_lengths():
    """
    比较不同数据长度对功率谱和PSD的影响
    """
    print("\n" + "="*70)
    print("不同数据长度的影响比较")
    print("="*70)

    sample_rate = 1000.0
    freq_signal = 100.0  # 测试信号频率

    # 不同的数据长度
    lengths = [512, 1024, 2048]

    for length in lengths:
        print(f"\n数据长度: {length} 样本")
        print("-" * 30)

        t = np.linspace(0, length/sample_rate, length, endpoint=False)
        signal = np.sin(2*np.pi*freq_signal*t)

        # 计算频率分辨率
        df = sample_rate / length
        print(f"频率分辨率: {df:.3f} Hz")

        # 计算功率谱和PSD
        freq_p, power_db, _ = calculate_power_spectrum_and_psd(signal, sample_rate, False)
        freq_psd, psd_db, _ = calculate_power_spectrum_and_psd(signal, sample_rate, True)

        # 找到信号频率附近的值
        idx = np.argmin(np.abs(freq_p - freq_signal))
        print(f"在{freq_signal}Hz附近:")
        print(f"  功率谱: {power_db[idx]:.1f} dB")
        print(f"  PSD: {psd_db[idx]:.1f} dB/Hz")


if __name__ == "__main__":
    # 演示功能
    demo_with_test_signal()
    compare_different_data_lengths()

    print("\n" + "="*70)
    print("关键公式总结:")
    print("="*70)
    print("1. 加窗: x_w[n] = x[n] × w[n]")
    print("2. FFT: X[k] = FFT(x_w[n])")
    print("3. 功率谱: P[k] = |X[k]|² / (N² × coherent_gain²)")
    print("4. 单边谱: P_single[k] = 2 × P[k]  (k > 0)")
    print("5. PSD: PSD[k] = P_single[k] / (df × noise_bandwidth)")
    print("6. dB: result = 10 × log10(P + ε)")
    print("\n其中:")
    print("  N = 数据长度")
    print("  w[n] = 窗函数（如Hanning窗）")
    print("  coherent_gain = sum(w[n]) / N")
    print("  noise_bandwidth = N × sum(w[n]²) / (sum(w[n]))²")
    print("  df = sample_rate / N  (频率分辨率)")
    print("  ε = 1e-20  (防止对数计算时为零)")