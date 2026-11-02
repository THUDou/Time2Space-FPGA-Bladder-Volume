import argparse
import struct
import sys
import time

import numpy as np

try:
    import serial
except ImportError:
    serial = None

SOUND_SPEED = 1480.0
SAMPLE_PERIOD = 40e-9
TOF_OFFSET = 13.43e-6
HDR = 7

NCH = 9

PITCH = 0.005
PROBE_XY = [(dx * PITCH, dy * PITCH) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]

def parse_stream(buf: bytearray):
    frames = []
    while True:
        i = buf.find(b"\xAA\x55")
        if i < 0:
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
    p = np.asarray(points, dtype=float)
    if len(p) < 4:
        raise ValueError("至少需要 4 个点")
    A = np.hstack([2 * p, np.ones((len(p), 1))])
    b = (p ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:3]
    r2 = (c ** 2).sum() + sol[3]
    if r2 <= 0:
        raise ValueError("拟合失败：半径为负，检查点位分布")
    r = np.sqrt(r2)
    return c, r, 4.0 / 3.0 * np.pi * r ** 3

def trilaterate(probes, dists):
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

    latest = {}
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
