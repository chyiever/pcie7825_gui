# WFBG-7825 寻峰（Peak Detection）原理分析

## 一、调用流程

从 C demo `WFBG7825_DEMO.c` 和 API 文档可梳理出两条寻峰调用路径：

**路径 A — 手动寻峰（Get Peak Info 按钮）：**

```
GetPeakInfoCB()                          // WFBG7825_DEMO.c:428
  → set_param()                          // 先配置所有硬件参数
  → get_peak_info_func(disp_en=1, save)  // 执行寻峰并显示结果
    → wfbg7825_get_peak_info(...)        // DLL 核心寻峰函数
  → run_get_peak_info = 1                // 标记已执行寻峰
```

**路径 B — 自动寻峰（START 时检查）：**

```
StartStopCB()                            // WFBG7825_DEMO.c:306
  → set_param()                          // 配置参数
  → if(run_get_peak_info==0)             // 若未手动寻峰
      get_peak_info_func(0, 0)           // 静默执行寻峰（不显示、不保存）
  → wfbg7825_get_valid_fbg_num(&fbg_num_per_ch)  // 获取有效FBG数量
  → wfbg7825_start()                     // 启动采集
```

核心约束：**`wfbg7825_start()` 之前必须调用 `get_peak_info` 或 `set_peak_info`**，这是硬件要求。

---

## 二、寻峰函数接口分析

### `wfbg7825_get_peak_info` 函数签名

```c
int wfbg7825_get_peak_info(
    unsigned int   amp_base_line,    // 输入：幅度阈值（典型值 2000）
    double         fbg_interval_m,   // 输入：光栅间距（米）
    unsigned int*  p_ch0_peak_cnt,   // 输出：CH0 峰值数量
    unsigned int*  p_ch0_peak_info,  // 输出：CH0 峰值索引 [point_num_per_scan]
    unsigned short* p_ch0_amp,       // 输出：CH0 幅值数据 [point_num_per_scan]
    unsigned int*  p_ch1_peak_cnt,   // 输出：CH1 峰值数量
    unsigned int*  p_ch1_peak_info,  // 输出：CH1 峰值索引 [point_num_per_scan]
    unsigned short* p_ch1_amp        // 输出：CH1 幅值数据 [point_num_per_scan]
);
```

**输入参数：**

- `amp_base_line`：幅度门限。低于此值的信号视为噪声，跳过不寻峰
- `fbg_interval_m`：光栅间距（单位：米）。用于约束相邻峰之间的最小距离

**输出数组：**

- `peak_info[i]`：二值数组，1 = 该位置是峰值（FBG 所在位置），0 = 非峰值
- `amp[i]`：经处理的幅值数据，最小值被钳位到 `amp_base_line`
- `peak_cnt`：检测到的峰值总数

**关键行为：** 函数内部会自动将峰值索引信息写入板卡（FPGA），因此理论上不需要再调用 `wfbg7825_set_peak_info()`。

---

## 三、C Demo 中的寻峰实现细节

从 `get_peak_info_func()`（WFBG7825_DEMO.c:520-576）可以看出：

```c
// 1. 分配与采样点数等长的数组
p_ch0_peak_info = (unsigned int *)malloc(total_point_num * sizeof(unsigned int));
p_ch0_amp = (unsigned short *)malloc(total_point_num * sizeof(unsigned short));

// 2. 调用 DLL 寻峰
wfbg7825_get_peak_info(amp_base_line, fbg_interval_m,
    &ch0_peak_cnt, p_ch0_peak_info, p_ch0_amp,
    &ch1_peak_cnt, p_ch1_peak_info, p_ch1_amp);

// 3. 显示时将 peak_info 放大 10000 倍叠加在幅值曲线上
for(i=0; i<total_point_num; i++) {
    p_ch0_peak_info[i] = p_ch0_peak_info[i] * 10000;  // 0→0, 1→10000
}
PlotY(... p_ch0_amp ...);        // 绿色：幅值包络
PlotY(... p_ch0_peak_info ...);  // 白色：峰值标记（脉冲柱）
```

显示效果：绿色曲线是光纤沿线的幅值分布，白色尖峰标出了每个 FBG 的位置。

---

## 四、物理原理

### 4.1 WFBG-DAS 系统工作原理

PCIe-WFBG-7825 是为**弱光纤光栅阵列分布式声波传感（WFBG-DAS）**专用的板卡。系统原理：

```
脉冲激光器 → AOM(声光调制,80/200MHz移频) → 光纤(串联弱FBG阵列)
                                                    ↓
光电探测器 ← 耦合器 ← FBG₁反射 + FBG₂反射 + ... + FBGₙ反射
    ↓
ADC(1GSps, 16bit) → FPGA(数字下变频 + 寻峰 + 相位解调)
```

每个触发脉冲发出后，光脉冲沿光纤传播，遇到每个弱 FBG 产生反射。由于光速有限，不同位置 FBG 的反射信号在时间上分开到达探测器。ADC 以 1GSps 采样，**时间轴上的采样点直接对应空间位置**：

$$\Delta x = \frac{c}{2 n_{\text{eff}} f_s} = \frac{3 \times 10^8}{2 \times 1.468 \times 10^9} \approx 0.1 \text{ m/点}$$

因此 `point_num_per_scan` 个采样点覆盖的光纤长度 = `point_num × 0.1m`。

### 4.2 幅值信号的物理含义

采集的原始信号是带有 AOM 调制频率（80/200MHz）的载波信号。经 FPGA 内部的数字 I/Q 解调后：

$$A(z) = \sqrt{I^2(z) + Q^2(z)}$$

得到沿光纤的幅值包络 `A(z)`。这个幅值曲线的物理含义：

- **FBG 位置处**：反射率强，幅值出现**局部极大值（峰值）**
- **FBG 之间**：仅有瑞利散射背景，幅值较低
- **光纤末端之后**：无信号，幅值接近噪底

因此，幅值曲线形状类似 OTDR 曲线，但上面叠加了等间距的尖峰（对应 FBG 阵列）。

### 4.3 寻峰算法推测

基于 API 参数和系统特征，可以推测 DLL 内部的寻峰算法：

**Step 1 — 多帧幅值平均（降噪）**

DLL 内部很可能采集多帧（如 1024 帧）幅值数据进行平均，以降低噪声抖动：

$$\bar{A}(z) = \frac{1}{N} \sum_{k=1}^{N} A_k(z)$$

这解释了为什么 `get_peak_info` 必须在 `start` 之前调用——它需要内部临时启动采集来收集多帧数据做平均。

**Step 2 — 门限滤波**

使用 `amp_base_line` 参数进行阈值过滤：

$$A'(z) = \begin{cases} \bar{A}(z) & \text{if } \bar{A}(z) \geq \text{amp\_base\_line} \\ \text{skip} & \text{otherwise} \end{cases}$$

低于门限的区域直接跳过，不参与后续寻峰。这排除了光纤末端噪声和 FBG 间的瑞利散射背景。

**Step 3 — 局部极大值检测**

在超过门限的区域中，寻找局部极大值。推测采用多点比较法（如 4 邻域比较）：

$$\text{isPeak}(i) = \begin{cases} 1 & \text{if } A'(i) > A'(i\pm1) \text{ and } A'(i) > A'(i\pm2) \\ 0 & \text{otherwise} \end{cases}$$

这适合 FPGA 并行实现——只需要移位寄存器和比较器。

**Step 4 — 间距约束（`fbg_interval_m` 的作用）**

`fbg_interval_m` 参数（单位：米）被转换为采样点数间距：

$$\Delta n = \frac{\text{fbg\_interval\_m}}{0.1 \text{ m/点}} = \text{fbg\_interval\_m} \times 10$$

例如 `fbg_interval_m = 5.0m` → 最小间距 50 个采样点。

作用：在检测到一个峰后，后续 `Δn` 个采样点内的其他局部极大值被抑制（类似非极大值抑制 / NMS）。这防止了单个 FBG 反射的旁瓣或多峰结构被误判为多个 FBG。

**Step 5 — 峰值索引写入 FPGA**

找到的峰值位置（`peak_info[i] = 1` 的索引）被编码并写入 FPGA 寄存器。后续 `phase_dem` 单元在实时解调时，**只对这些峰值位置的 I/Q 数据进行相位提取**，而不是对所有采样点做相位解调。这就是为什么：

- 相位数据大小 = `fbg_num_per_ch`（峰值数量），而非 `point_num_per_scan`
- `phase_dem` 单元最大处理 16384 个 FBG 点（硬件资源限制）

---

## 五、寻峰在数据流中的角色

```
            全部采样点 (point_num_per_scan)
原始/幅值数据: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                 ↑    ↑    ↑    ↑    ↑         ← FBG 峰值位置

                 寻峰筛选 ↓

相位数据:        ●    ●    ●    ●    ●         ← fbg_num_per_ch 个点
                 (phase_dem 只提取峰值处的相位)
```

这是 7825 相对于通用 DAS 板卡（如 7821）的核心区别：**7821 对所有采样点做相位解调（数据量大），而 7825 通过寻峰只对 FBG 位置做相位解调（数据量大幅压缩，且信噪比更高）**。

---

## 六、`wfbg7825_set_peak_info` 的作用

API 文档说明：用户可以用自己的寻峰算法替代内置算法——先调用 `get_peak_info` 获取幅值数据 `amp[]`，用自定义算法生成 `peak_info[]`，再通过 `set_peak_info` 写入板卡。这提供了算法可扩展性，但一般情况下内置算法已足够。

---

## 七、总结

| 方面 | 推测结论 |
|------|----------|
| **输入数据** | 内部临时采集多帧幅值 √(I²+Q²)，做帧平均降噪 |
| **门限过滤** | `amp_base_line` 排除噪声区域 |
| **峰值检测** | 多点邻域比较寻找局部极大值 |
| **间距约束** | `fbg_interval_m` → 最小点间距，抑制旁瓣/伪峰 |
| **输出** | 二值索引数组 + 峰值计数，自动写入 FPGA |
| **核心价值** | 将 O(point_num) 的全量采样压缩为 O(fbg_num) 的稀疏相位解调，提高效率和信噪比 |

---

## 参考文件

- `PCIe-WFBG-7825/doc/readme.txt` — API 接口文档，函数 10-12 描述寻峰相关接口
- `PCIe-WFBG-7825/windows issue/demo/WFBG_7825_Dem_dll_ver/WFBG7825_DEMO.c` — C 语言上位机 Demo，`get_peak_info_func()` (line 520-576)、`GetPeakInfoCB()` (line 428-451)、`StartStopCB()` (line 306-426)
