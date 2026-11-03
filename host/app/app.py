#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Time2Space 膀胱尿量估计系统 — 上位机（演示 + 实测双模式）

启动：
    python app.py              # 自动打开浏览器，进入演示模式
    python app.py --port 8787  # 指定端口
    python app.py --no-browser # 不自动开浏览器

数据链路（两手方案，软件侧完全一致，都是标准串口）：
    方案 A  蓝牙：HC-05/HC-04 模块接 PYNQ JB8(W15) -> PC 配对出 COM 口
    方案 B  有线：USB-TTL (CH340/CP2102) 接 JB8(W15) -> PC 直接出 COM 口
    演示模式：无硬件时用内置合成回波，界面与实测完全同构。

依赖：Python 3.8+ 标准库即可运行；接真实串口需 `pip install pyserial`。
"""
import argparse
import json
import math
import os
import random
import re
import struct
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ---------------- 与 RTL / host_monitor 一致的常量 ----------------
SOUND_SPEED = 1480.0        # m/s
SAMPLE_PERIOD = 40e-9       # 25 MSPS
TOF_OFFSET = 13.43e-6       # 发射+阻塞窗口
NCH = 9
PITCH = 0.025               # 阵元中心距 25 mm
PROBE_XY = [(dx * PITCH, dy * PITCH) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
BAUD = 460800

try:
    import serial  # type: ignore
    from serial.tools import list_ports  # type: ignore
    HAVE_SERIAL = True
except ImportError:
    HAVE_SERIAL = False


# ---------------- 帧解析（与 frame_sender.v 对应） ----------------
HDR = 7  # AA 55 CH TOF_L TOF_H PEAK_L PEAK_H


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
        ch = frame[2]
        tof = struct.unpack_from("<H", frame, 3)[0]
        peak = struct.unpack_from("<H", frame, 5)[0]
        wave = list(frame[HDR:HDR + 256])
        frames.append({"ch": ch, "tof": tof, "peak": peak, "wave": wave})
        buf = buf[i + HDR + 256 + 1:]
    return frames, buf


def tof_to_dist_m(tof_samples: float) -> float:
    t = tof_samples * SAMPLE_PERIOD + TOF_OFFSET
    return SOUND_SPEED * t / 2.0


def sphere_fit(points):
    import numpy as np  # 延迟导入，演示模式不强依赖
    p = np.asarray(points, dtype=float)
    A = np.hstack([2 * p, np.ones((len(p), 1))])
    b = (p ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:3]
    r2 = sol[3] + (c ** 2).sum()
    if r2 <= 0:
        raise ValueError("sphere fit failed")
    r = math.sqrt(float(r2))
    return c, r, 4.0 / 3.0 * math.pi * r ** 3


def sphere_fit_pure(points):
    """无 numpy 回退：高斯消元 4x4 最小二乘球面拟合"""
    n = len(points)
    if n < 4:
        raise ValueError("need >=4 points")
    # 设计矩阵 A(n x 4): [2x, 2y, 2z, 1], b = x^2+y^2+z^2
    AtA = [[0.0] * 4 for _ in range(4)]
    Atb = [0.0] * 4
    for (x, y, z) in points:
        row = (2 * x, 2 * y, 2 * z, 1.0)
        bb = x * x + y * y + z * z
        for i in range(4):
            Atb[i] += row[i] * bb
            for j in range(4):
                AtA[i][j] += row[i] * row[j]
    # 高斯消元
    M = [AtA[i] + [Atb[i]] for i in range(4)]
    for i in range(4):
        piv = max(range(i, 4), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            raise ValueError("singular")
        M[i], M[piv] = M[piv], M[i]
        for r in range(4):
            if r != i and M[i][i] != 0:
                f = M[r][i] / M[i][i]
                for c in range(i, 5):
                    M[r][c] -= f * M[i][c]
    sol = [M[i][4] / M[i][i] for i in range(4)]
    cx, cy, cz = sol[0], sol[1], sol[2]
    r2 = sol[3] + cx * cx + cy * cy + cz * cz
    if r2 <= 0:
        raise ValueError("bad fit")
    r = math.sqrt(r2)
    return (cx, cy, cz), r, 4.0 / 3.0 * math.pi * r ** 3


# ---------------- 演示数据引擎 ----------------
class DemoEngine:
    """合成膀胱回波：球体充盈缓慢变化 + 呼吸起伏 + 噪声，指标全部走真实公式。"""

    def __init__(self):
        self.t0 = time.time()
        self.rng = random.Random(48878)
        self.history = []      # [(t, volume_ml)]
        self.frames_total = 0
        self.fps = 0.0
        self._fps_mark = time.time()
        self._fps_cnt = 0

    def _bladder(self, t):
        """返回 (center(x,y,z) m, radius m, volume_ml)"""
        vol_ml = 300.0 + 110.0 * math.sin(t * 0.045) + 8.0 * math.sin(t * 0.9)
        r = ((vol_ml * 1e-6) * 3.0 / (4.0 * math.pi)) ** (1.0 / 3.0)
        cx = 0.0015 * math.sin(t * 0.11)
        cy = 0.0012 * math.cos(t * 0.09)
        cz = 0.076 + 0.0022 * math.sin(t * 0.55)  # 呼吸起伏
        return (cx, cy, cz), r, vol_ml

    @staticmethod
    def _ray_hit(px, py, pz, nx, ny, nz, c, r):
        """射线-球：返回到前壁距离 t（取较小正根）"""
        dx, dy, dz = px - c[0], py - c[1], pz - c[2]
        b = dx * nx + dy * ny + dz * nz
        cc = dx * dx + dy * dy + dz * dz - r * r
        disc = b * b - cc
        if disc < 0:
            return None
        sq = math.sqrt(disc)
        t1 = -b - sq
        t2 = -b + sq
        if t1 > 0:
            return t1
        if t2 > 0:
            return t2
        return None

    @staticmethod
    def _wave_for(tof, peak, rng):
        pos = tof / 16.0  # 256 点 = 4096 采样抽取
        w = []
        for i in range(256):
            v = 26.0 + rng.gauss(0, 5)
            g1 = peak * math.exp(-((i - pos) ** 2) / (2 * 5.5 ** 2))
            g2 = 0.55 * peak * math.exp(-((i - pos - 34) ** 2) / (2 * 7.0 ** 2))  # 后壁
            v += g1 + g2
            w.append(max(0, min(255, int(v))))
        return w

    def snapshot(self):
        t = time.time() - self.t0
        c, r, vol_ml = self._bladder(t)
        tof, dist_cm, peak, waves, pts = [], [], [], [], []
        # 球冠探头：中心 z 偏移 8mm 拱高，声轴指向焦点 (0,0,0.082)
        for (x, y) in PROBE_XY:
            pz = 0.008 - 0.008  # 平面近似（球冠高 8mm 对 TOF 影响已含在几何标定）
            fx, fy, fz = 0.0, 0.0, 0.082
            nx, ny, nz = fx - x, fy - y, fz - pz
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            nx, ny, nz = nx / ln, ny / ln, nz / ln
            hit = self._ray_hit(x, y, pz, nx, ny, nz, c, r)
            d = hit if hit else 0.06
            # 钳在合理膀胱深度窗
            d = min(max(d, 0.025), 0.115)
            ts = max(0, min(4095, int(round((2 * d / SOUND_SPEED - TOF_OFFSET) / SAMPLE_PERIOD))))
            pk = int(max(60, min(255, 205 + 28 * math.sin(t * 1.7 + x * 40) + self.rng.gauss(0, 6))))
            tof.append(ts)
            dist_cm.append(d * 100.0)
            peak.append(pk)
            waves.append(self._wave_for(ts, pk, self.rng))
            # 重建点：探头位置 + 距离 * 声轴
            pts.append([x + d * nx, y + d * ny, pz + d * nz])

        # 用重建点做球面拟合 -> 容积（与实测同一条公式链）
        try:
            try:
                import numpy  # noqa: F401
                cc2, rr2, vv = sphere_fit(pts)
            except ImportError:
                cc2, rr2, vv = sphere_fit_pure(pts)
            fit_vol_ml = vv * 1e6
            fit_r_mm = rr2 * 1e3
            fit_c_mm = [cc2[0] * 1e3, cc2[1] * 1e3, cc2[2] * 1e3]
        except Exception:
            fit_vol_ml, fit_r_mm, fit_c_mm = vol_ml, r * 1e3, [c[0] * 1e3, c[1] * 1e3, c[2] * 1e3]

        self.frames_total += NCH
        self._fps_cnt += NCH
        now = time.time()
        dt = now - self._fps_mark
        self.fps = self._fps_cnt / dt if dt > 0 else 0.0
        if dt >= 1.0:
            self._fps_mark = now
            self._fps_cnt = 0

        self.history.append((now, fit_vol_ml))
        if len(self.history) > 240:
            self.history = self.history[-240:]

        return {
            "mode": "demo",
            "connected": True,
            "label": "演示模式 · 合成回波",
            "volume_ml": round(fit_vol_ml, 1),
            "radius_mm": round(fit_r_mm, 1),
            "center_mm": [round(v, 1) for v in fit_c_mm],
            "tof": tof,
            "dist_cm": [round(v, 2) for v in dist_cm],
            "peak": peak,
            "wave": waves,
            "points": [[round(v, 4) for v in p] for p in pts],
            "history": [[round(t, 2), round(v, 1)] for t, v in self.history],
            "stats": {"fps": round(self.fps, 1), "frames": self.frames_total,
                      "rate": f"{self.fps:.0f} 帧/秒"},
        }


# ---------------- 串口引擎 ----------------
class SerialEngine(threading.Thread):
    def __init__(self, port, baud):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.buf = bytearray()
        self.latest = {}      # ch -> frame
        self.lock = threading.Lock()
        self.running = True
        self.frames_total = 0
        self.fps = 0.0
        self._fps_cnt = 0
        self._fps_mark = time.time()
        self.history = []
        self.error = None
        self.ser = None

    def run(self):
        if not HAVE_SERIAL:
            self.error = "缺少 pyserial，请先 pip install pyserial"
            self.running = False
            return
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
        except Exception as e:
            self.error = f"串口打开失败：{e}"
            self.running = False
            return
        while self.running:
            try:
                chunk = self.ser.read(1024)
            except Exception as e:
                self.error = f"串口读取失败：{e}"
                break
            if chunk:
                self.buf.extend(chunk)
                frames, self.buf = parse_stream(self.buf)
                if frames:
                    with self.lock:
                        for fr in frames:
                            self.latest[fr["ch"] % NCH] = fr
                        self.frames_total += len(frames)
                        self._fps_cnt += len(frames)
            now = time.time()
            if now - self._fps_mark >= 1.0:
                self.fps = self._fps_cnt / (now - self._fps_mark)
                self._fps_mark = now
                self._fps_cnt = 0
                self._maybe_volume()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass

    def _maybe_volume(self):
        with self.lock:
            if len(self.latest) < NCH:
                return
            pts = []
            for ch in range(NCH):
                fr = self.latest.get(ch)
                if not fr:
                    return
                x, y = PROBE_XY[ch]
                d = tof_to_dist_m(fr["tof"])
                fx, fy, fz = 0.0, 0.0, 0.082
                nx, ny, nz = fx - x, fy - y, fz
                ln = math.sqrt(nx * nx + ny * ny + nz * nz)
                pts.append([x + d * nx / ln, y + d * ny / ln, d * nz / ln])
        try:
            try:
                import numpy  # noqa: F401
                c, r, v = sphere_fit(pts)
            except ImportError:
                c, r, v = sphere_fit_pure(pts)
            self.history.append((time.time(), v * 1e6))
            if len(self.history) > 240:
                self.history = self.history[-240:]
            self._fit = (c, r, v)
        except Exception:
            pass

    def stop(self):
        self.running = False

    def snapshot(self):
        with self.lock:
            latest = dict(self.latest)
        tof, dist_cm, peak, waves, pts = [], [], [], [], []
        for ch in range(NCH):
            fr = latest.get(ch)
            if fr:
                d = tof_to_dist_m(fr["tof"])
                tof.append(fr["tof"])
                dist_cm.append(round(d * 100, 2))
                peak.append(fr["peak"])
                waves.append(fr["wave"])
                x, y = PROBE_XY[ch]
                fx, fy, fz = 0.0, 0.0, 0.082
                nx, ny, nz = fx - x, fy - y, fz
                ln = math.sqrt(nx * nx + ny * ny + nz * nz)
                pts.append([x + d * nx / ln, y + d * ny / ln, d * nz / ln])
            else:
                tof.append(0)
                dist_cm.append(0)
                peak.append(0)
                waves.append([0] * 256)
                pts.append([0, 0, 0])
        vol, rr, cc = None, None, None
        if getattr(self, "_fit", None):
            c, r, v = self._fit
            vol, rr, cc = v * 1e6, r * 1e3, [c[0] * 1e3, c[1] * 1e3, c[2] * 1e3]
        return {
            "mode": "serial",
            "connected": self.running and self.error is None,
            "label": f"串口 {self.port} @ {self.baud}",
            "error": self.error,
            "volume_ml": round(vol, 1) if vol else 0,
            "radius_mm": round(rr, 1) if rr else 0,
            "center_mm": [round(x, 1) for x in cc] if cc else [0, 0, 0],
            "tof": tof,
            "dist_cm": dist_cm,
            "peak": peak,
            "wave": waves,
            "points": pts,
            "history": [[round(t, 2), round(v, 1)] for t, v in self.history],
            "stats": {"fps": round(self.fps, 1), "frames": self.frames_total,
                      "rate": f"{self.fps * 1:.0f} 帧/秒"},
        }


# ---------------- 全局状态 ----------------
class State:
    def __init__(self):
        self.demo = DemoEngine()
        self.serial_eng = None
        self.lock = threading.Lock()

    def connect(self, mode, port, baud):
        with self.lock:
            if self.serial_eng:
                self.serial_eng.stop()
                self.serial_eng = None
            if mode == "serial":
                if not port:
                    raise ValueError("未选择串口")
                self.serial_eng = SerialEngine(port, int(baud))
                self.serial_eng.start()
        return {"ok": True}

    def disconnect(self):
        with self.lock:
            if self.serial_eng:
                self.serial_eng.stop()
                self.serial_eng = None
        return {"ok": True}

    def snapshot(self):
        with self.lock:
            eng = self.serial_eng
        if eng and eng.running:
            snap = eng.snapshot()
            if snap.get("error"):
                snap["connected"] = False
            return snap
        return self.demo.snapshot()


STATE = State()


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, self._read("index.html"), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(200, json.dumps(STATE.snapshot(), ensure_ascii=False))
        if path == "/api/ports":
            ports = []
            if HAVE_SERIAL:
                try:
                    ports = [{"device": p.device, "desc": p.description}
                             for p in list_ports.comports()]
                except Exception:
                    ports = []
            return self._send(200, json.dumps({"ports": ports, "have_serial": HAVE_SERIAL}))
        # 静态文件
        fname = path.lstrip("/")
        fpath = os.path.normpath(os.path.join(STATIC_DIR, fname))
        if not fpath.startswith(STATIC_DIR) or not os.path.isfile(fpath):
            return self._send(404, "not found", "text/plain")
        ctype = {"css": "text/css; charset=utf-8",
                 "js": "application/javascript; charset=utf-8",
                 "svg": "image/svg+xml",
                 "png": "image/png",
                 "html": "text/html; charset=utf-8"}.get(fname.rsplit(".", 1)[-1], "application/octet-stream")
        with open(fpath, "rb") as f:
            return self._send(200, f.read(), ctype)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, json.dumps({"ok": False, "error": "bad json"}))
        path = self.path.split("?")[0]
        try:
            if path == "/api/connect":
                res = STATE.connect(body.get("mode", "demo"),
                                    body.get("port"), body.get("baud", BAUD))
                return self._send(200, json.dumps(res))
            if path == "/api/disconnect":
                return self._send(200, json.dumps(STATE.disconnect()))
        except Exception as e:
            return self._send(200, json.dumps({"ok": False, "error": str(e)}))
        return self._send(404, json.dumps({"ok": False}))

    def _read(self, name):
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            return f.read()


def main():
    ap = argparse.ArgumentParser(description="Time2Space 上位机")
    ap.add_argument("--port", type=int, default=8787, help="HTTP 端口（默认 8787）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 56)
    print("  Time2Space 膀胱尿量估计系统 · 上位机")
    print(f"  地址: {url}")
    print("  模式: 演示模式（默认） / 串口直连 / 蓝牙串口")
    print("  退出: Ctrl+C")
    print("=" * 56)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()
