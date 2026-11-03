#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Time2Space 超声三维测距 — 上位机监视器（v0.1）

帧格式（与 frame_sender.v 对应，小端）：
    AA 55 | CH | TOF_L TOF_H | PEAK_L PEAK_H | S0..S255 | 0D
CH = 通道号 0..8（3x3 探头阵列），一轮 9 帧拼成一组送球面拟合

用法：
    python host_monitor.py --port COM5 --baud 460800
    python host_monitor.py --port COM5 --csv data.csv

依赖：pyserial, matplotlib, numpy
"""
import argparse
import struct
import sys
import time

import numpy as np

try:
    import serial
except ImportError:
    serial = None

SOUND_SPEED = 1480.0      # m/s，水中声速，可按水温修正
SAMPLE_PERIOD = 40e-9     # 25MSPS -> 40ns/点
TOF_OFFSET = 13.43e-6     # 发射脉冲(3.43us)+阻塞(10us)，需实测标定
HDR = 7                   # AA 55 CH TOF_L TOF_H PEAK_L PEAK_H

NCH = 9                   # 一轮扫描的通道数（与 RTL 的 NCH 一致）

# 3x3 阵列各探头坐标（单位：米，阵列平面 z=0，探头朝 +z）
# 本项目机械基线：PZT 直径 5mm，阵列中心距 25mm，球面冠 R=82mm
# PITCH 必须按实装探头中心距实测填写；默认 0.025m = 25mm
PITCH = 0.025
PROBE_XY = [(dx * PITCH, dy * PITCH) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


def parse_stream(buf: bytearray):
    """从缓冲区中提取完整帧，返回 (frames, 剩余buf)"""
    frames = []
    while True:
        i = buf.find(b"\xAA\x55")
        if i < 0:
            # 保留最后 1 字节，避免帧头被截断
            return frames, buf[-1:]
        if len(buf) < i + HDR + 256 + 1:
            return frames, buf[i:]
        frame = buf[i:i + HDR + 256 + 1]
        if frame[-1] != 0x0D:
            buf = buf[i + 1:]
            continue
        ch   = frame[2]
        tof  = struct.unpack_from("<H", frame, 3)[0]
        peak = struct.unpack_from("<H", frame, 5)[0]
        wave = np.frombuffer(frame[HDR:HDR + 256], dtype=np.uint8).astype(np.int16)
        frames.append({"ch": ch, "tof": tof, "peak": peak, "wave": wave})
        buf = buf[i + HDR + 256 + 1:]
    return frames, buf


def tof_to_distance_m(tof_samples: int) -> float:
    t = tof_samples * SAMPLE_PERIOD + TOF_OFFSET
    return SOUND_SPEED * t / 2.0


def sphere_fit(points):
    """
    线性化最小二乘球面拟合（与 PL 实现同一算法）
    |p|^2 - 2c·p + (|c|^2 - r^2) = 0
    未知量 [a,b,d,e] = [-2cx,-2cy,-2cz, |c|^2-r^2]
    """
    p = np.asarray(points, dtype=float)
    if len(p) < 4:
        raise ValueError("至少需要 4 个点")
    A = np.hstack([2 * p, np.ones((len(p), 1))])
    b = (p ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:3]                      # 2c·p 的系数即 c
    r2 = (c ** 2).sum() + sol[3]     # e = r^2 - |c|^2
    if r2 <= 0:
        raise ValueError("拟合失败：半径为负，检查点位分布")
    r = np.sqrt(r2)
    return c, r, 4.0 / 3.0 * np.pi * r ** 3


def trilaterate(probes, dists):
    """
    多点测距定位（与 PL 端同一套线性化最小二乘）
    已知探头位置 p_i、测得距离 d_i，解目标点 t：
        |t - p_i| = d_i
        => |t|^2 - 2 p_i·t + |p_i|^2 = d_i^2
        => 2 p_i·t - s = |p_i|^2 - d_i^2      (s = |t|^2)
    未知量 [tx, ty, tz, s]，最少 4 路，9 路冗余抗病态。
    """
    P = np.asarray(probes, dtype=float)
    d = np.asarray(dists, dtype=float)
    if len(P) < 4:
        raise ValueError("至少需要 4 路测距")
    A = np.hstack([2 * P, -np.ones((len(P), 1))])
    b = (P ** 2).sum(axis=1) - d ** 2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    t = sol[:3]
    resid = np.sqrt(((A @ sol - b) ** 2).mean())
    return t, resid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=False, help="串口，如 COM5")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--csv", default=None, help="保存原始数据到 csv")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    if args.port and serial is None:
        print("请先安装 pyserial: pip install pyserial", file=sys.stderr)
        return 1

    plot = not args.no_plot
    if plot:
        import matplotlib.pyplot as plt
        plt.ion()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
        line, = ax1.plot(np.arange(256) * 16 * SAMPLE_PERIOD * 1e6, np.zeros(256))
        ax1.set_xlabel("time (us)")
        ax1.set_ylabel("ADC code")
        ax1.set_title("echo waveform (256 pts, decimated)")
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(0, 260)

    buf = bytearray()
    ser = None
    if args.port:
        ser = serial.Serial(args.port, args.baud, timeout=0.05)
        print(f"opened {args.port} @ {args.baud}")

    csv_f = open(args.csv, "w", encoding="utf-8") if args.csv else None
    if csv_f:
        csv_f.write("ch,tof,peak," + ",".join(f"s{i}" for i in range(256)) + "\n")

    latest = {}          # ch -> (tof, peak, dist_m)
    last = time.time()
    fps = 0
    try:
        while True:
            if ser:
                chunk = ser.read(512)
                buf.extend(chunk)
            else:
                time.sleep(0.05)
                continue

            frames, buf = parse_stream(buf)
            for fr in frames:
                d = tof_to_distance_m(fr["tof"])
                ch = fr["ch"]
                print(f"CH{ch}  TOF={fr['tof']:4d}  dist={d*100:7.2f} cm  peak={fr['peak']:3d}")
                if csv_f:
                    csv_f.write(f"{ch},{fr['tof']},{fr['peak']}," +
                                ",".join(map(str, fr["wave"])) + "\n")
                if plot:
                    line.set_ydata(fr["wave"])
                    ax1.set_title(f"CH{ch}  TOF={fr['tof']}  d={d*100:.2f}cm  peak={fr['peak']}")
                    fig.canvas.draw_idle()
                    fig.canvas.flush_events()

                latest[ch] = (fr["tof"], fr["peak"], d)
                # 收集满一轮（默认 9 路）-> 三维定位
                if len(latest) >= NCH and all(k in latest for k in range(NCH)):
                    probes = []
                    dists = []
                    for k in range(NCH):
                        x, y = PROBE_XY[k]
                        probes.append([x, y, 0.0])
                        dists.append(latest[k][2])
                    try:
                        t, resid = trilaterate(probes, dists)
                        print(f"  >> 目标 3D 位置: x={t[0]*100:7.2f} y={t[1]*100:7.2f} "
                              f"z={t[2]*100:7.2f} cm   |r|={np.linalg.norm(t)*100:6.2f} cm  "
                              f"残差={resid*1000:.2f} (mm^2量纲)")
                    except ValueError as e:
                        print("  >> 定位失败:", e)
                    latest.clear()

            fps += 1
            if time.time() - last > 1.0:
                last = time.time()
                fps = 0
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        if csv_f:
            csv_f.close()
        if ser:
            ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
