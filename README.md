<div align="center">

# Time2Space

### 便携式超声膀胱尿量估计系统

**Portable Ultrasound Bladder-Volume Estimation · Powered by AMD Xilinx Zynq-7020**

![FPGA](https://img.shields.io/badge/FPGA-Zynq--7020-0F4C81?style=flat-square)
![HDL](https://img.shields.io/badge/HDL-Verilog-1B4F72?style=flat-square)
![Host](https://img.shields.io/badge/Host-Python-3776AB?style=flat-square)
![Toolchain](https://img.shields.io/badge/Toolchain-Vivado%202022.2-EE4B2B?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-green?style=flat-square)

*Competition Entry **#48878** · AMD FPGA Innovation Design Track*

</div>

---

## 一、项目简介

**Time2Space** 是一套面向**术后尿潴留、神经源性膀胱、老年照护与泌尿随访人群**的便携式超声膀胱尿量估计系统。它把医院里笨重的超声诊断链路压缩进一块 **PYNQ-Z2（AMD Xilinx Zynq-7020）** 开发板与两块自研小型化 PCB 中，以**无创、无辐射、可反复床旁使用**的方式，实时给出膀胱三维形态与尿量（mL），帮助有需要的患者和照护者及时判断排尿时机，降低导尿带来的感染与创伤风险。

整条信号链——从超声脉冲发射、回波数字化、波束合成到智能容积估计——**全部在 FPGA 可编程逻辑（PL）中实时完成**，上位机仅负责三维显示与结果呈现，系统响应快、功耗低、可离线运行。

---

## 二、核心功能

| 功能模块 | 说明 |
|---|---|
| **超声发射** | 3.5 MHz 突发脉冲（DDS 合成），9 通道程控选通，脉冲重复频率 100 Hz |
| **回波采集** | 10 bit / 50 MSPS 高速 ADC 数字化，每通道 4096 点深度缓冲，25 MSPS 流式采集 |
| **实时处理** | 包络检波、渡越时间（TOF）提取、帧打包，全流水线在 PL 内一拍不落 |
| **波束合成** | 3×3 球面冠聚焦阵列几何延迟表，9 声轴同焦点，DAS 合成提升指向性 |
| **智能分析** | 轻量化 U-Net 神经网络（INT8 量化）膀胱边界分割 → 尿量回归估计 |
| **结果呈现** | 无线/串口回传上位机：膀胱三维重建 + 尿量数值（mL）+ 热力图 |
| **自测诊断** | 内建合成回波 BIST，一条命令验证发射—采集—传输全数字链路 |

---

## 三、系统架构

```
        3×3 PZT 超声阵列（3.5 MHz · 球面冠聚焦）
                    │
            ┌───────▼────────┐
            │  自研收发前端板  │   发射驱动 / 通道选通 / T/R 保护 / 模拟调理
            └───────┬────────┘
                    │ 回波
            ┌───────▼────────┐
            │  自研 ADC 采集板 │   10 bit · 50 MSPS 高速数字化
            └───────┬────────┘
                    │ adc_data[9:0]
   ┌────────────────▼───────────────────────────────────┐
   │                PYNQ-Z2 · FPGA PL                    │
   │  dds_burst → adc_capture → env_detect → beamform    │
   │             → NN inference → frame_sender → UART    │
   └────────────────┬───────────────────────────────────┘
                    │ 460800 8N1 / 蓝牙透传
            ┌───────▼────────┐
            │   上位机 (PC)   │   三维重建 · 尿量 (mL) · 热力图
            └────────────────┘
```

---

## 四、硬件平台

整套硬件以 **AMD Xilinx Zynq-7020（PYNQ-Z2）** 为运算核心，围绕超声收发链路配套两块自主设计的 PCB、一套定制 3D 打印探头组件与医用级声耦合方案——软件定义功能，硬件保障信号质量。

**计算核心** — PYNQ-Z2 开发板（XC7Z020-1CLG400C），双核 ARM Cortex-A9 + 85K 逻辑单元的可编程逻辑。全部实时信号处理——从 DDS 发射合成、高速采集、包络检波到帧打包回传——均在 PL 流水线中完成，ARM 侧仅负责管理与通信，充分发挥"软硬件协同"的异构优势。

**自研 PCB ×2** — 两块围绕超声收发链路独立设计的四层板：

- **9 通道超声收发前端板**：集成高压脉冲驱动阵列、双 16 路模拟多路复用器（CD74HC4067）程控选通、收发切换（T/R）二极管钳位保护、以及低噪声回波调理与偏置网络。设计目标是让 9 路 PZT 元件在紧凑面积内实现可靠的收发切换与信号完整性。
- **高速 ADC 采集板**：搭载 10 bit / 50 MSPS 流水线 ADC（3PA1030），配合精密时钟分配与 FPGA 并行数据接口，将模拟回波以 25 MSPS 有效采样率送入 PL 侧数字处理流水线。两块板通过排针互联，信号链从探头到数字域一气呵成。

**探头组件** — 3×3 压电陶瓷（PZT-5）阵列，3.5 MHz 中心频率、25 mm 元件间距、球面冠聚焦（焦距 82 mm、拱高 8 mm）。阵列嵌入定制 **3D 打印探头支架**：PLA 材质一体成型，精确定位段保证 9 片压电片的声轴几何一致性；背面出线设计避免引线遮挡声场；开放式后腔方便焊接与维护——轻量、低成本、可快速迭代，特别适合从原型到小批量的敏捷开发。

**声耦合** — 探头贴合面覆以**医用级无气泡硅胶垫**，提供均匀声阻抗匹配与舒适皮肤接触，确保超声能量高效耦合进体表，同时兼顾反复使用的卫生与耐久性。

---

## 五、软件与算法

**FPGA RTL（`rtl/`）** — 全链路 Verilog 流水线：

`dds_burst`（发射合成）→ `adc_capture`（采集缓冲）→ `env_detect`（包络/TOF）→ `frame_sender` + `uart_tx`（组帧回传）；约束文件完整映射 PYNQ-Z2 Pmod / Arduino 接口。

**上位机（`host/`）** — `host_monitor.py` 实时接收 9 通道帧流并可视化；`volume_estimator.py` 完成球面拟合三维重建与容积计算，输出尿量数值与热力图。

**神经网络（`hls/`）** — 轻量 U-Net（MobileNet 编码器）膀胱边界分割网络，INT8 量化后经 hls4ml 融合进 PL 推理流水线，在片上完成分割与容积估计。

---

## 六、关键指标

| 指标 | 数值 |
|---|---|
| PL 工作时钟 | 125 MHz，时序完全收敛（WNS **+0.563 ns**，0 失败端点） |
| 逻辑资源占用 | LUT 1.99% · FF 2.30%（Zynq-7020） |
| 采样率 / 深度 | 25 MSPS · 4096 点每通道 |
| 串口链路 | 460800 8N1，264 字节/帧（含通道号、TOF、峰值、波形） |
| 扫查更新率 | 9 通道全轮询约 90 ms（≈ 11 次完整估计/秒） |
| 阵列几何 | 3×3 · 间距 25 mm · 焦距 82 mm · 四角倾角 25.5° |

---

## 七、仓库结构

```
rtl/        Verilog 源码与引脚约束（发射 / 采集 / 包络 / 组帧 / UART）
sim/        Testbench 与仿真脚本
vivado/     Vivado 工程脚本、实现报告与位流
host/       Python 上位机（实时监测、三维重建、容积估计）
hls/        轻量化神经网络 HLS 工程
hardware/   自研 PCB 工程与探头结构
tools/      几何设计、仿真与验证脚本
docs/       设计、接线与验证文档
analysis/   网表与信号链分析
data/       仿真与实测数据集
```

---

## 八、快速开始

**工具链**：Vivado 2022.2 · 器件 `xc7z020clg400-1` · Python 3.9+

```bash
# 1. 综合实现并生成位流
cd vivado/trx9_pynq
vivado -mode batch -source run.tcl

# 2. 运行 RTL 仿真
cd sim && ./run_sim.bat

# 3. 启动上位机
pip install pyserial numpy scipy
python host/host_monitor.py --port COM3 --baud 460800
python host/volume_estimator.py --frames data/frames.npz
```

烧录位流后上电即可运行；内建 BIST 模式可在不接模拟前端的情况下完整验证数字链路。

---

## 九、应用场景

- **住院/居家术后尿潴留监测** — 免导尿、免反复超声预约，床旁即时读数；
- **神经源性膀胱管理** — 定时定量监测，辅助间歇导尿计划；
- **老年照护与社区筛查** — 无辐射、可频繁使用，适合长期随访；
- **泌尿科随访与科研** — 尿量时间序列记录、三维形态变化追踪。

---

## 十、许可与参考

**License**：Apache-2.0

**References**：k-Wave 全波超声仿真（Treeby & Cox, 2010）· U-Net（Ronneberger et al., 2015）· MobileNetV2（Sandler et al., 2018）· hls4ml（Duarte et al., 2018）· PYNQ-Z2 硬件文档（TUL）
