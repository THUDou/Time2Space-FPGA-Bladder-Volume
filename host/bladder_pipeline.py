# -*- coding: utf-8 -*-
"""主机侧完整链路：9 通道 RF → DAS 波束合成 → B-mode → U-Net 分割 → 容积(mL)。

用法:
  python host/bladder_pipeline.py --npz data/kwave/bladder_kwave_9ch_200ml.npz
  python host/bladder_pipeline.py --selftest        # 用合成数据自检
"""
import os, sys, json, math, argparse
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "E:/sim_env")
sys.path.insert(0, os.path.join(ROOT, "tools"))

# ---- 与训练数据一致的栅格 ----
W_MM, D_MM = 80.0, 140.0
GRID = 128
DX, DZ = W_MM / GRID, D_MM / GRID
MASK_N = 64
PIX_X, PIX_Z = W_MM / MASK_N, D_MM / MASK_N

C_TISSUE = 1500.0      # 波束合成用的平均声速（mm/us -> 1.5 mm/us）
R_CAP = 82.0
PITCH = 25.0


def ch_positions():
    """3x3 球冠阵列的 (x, z) 坐标，单位 mm。行/列顺序与 RTL 扫描一致：r0c0..r2c2。"""
    out = []
    for r, y in enumerate((-PITCH, 0.0, PITCH)):
        for c, x in enumerate((-PITCH, 0.0, PITCH)):
            z = R_CAP - math.sqrt(max(R_CAP ** 2 - (x * x + y * y), 0.0))
            out.append((x, z))
    return out


def tgc(rf, t_us, t0=6.0, power=1.6):
    g = np.clip(t_us / t0, 1.0, None) ** power
    out = rf.astype(np.float64) * g
    out[t_us < t0] *= 0.02
    return out


def das_image(rfs, t, positions=None, grid=GRID):
    """多通道脉冲回波 DAS：I(x,z) = Σ_k rf_k(2·d_k/c)。"""
    if positions is None:
        positions = ch_positions()
    n = rfs.shape[0]
    dt_us = float(t[1] - t[0]) * 1e6 if t[1] < 1e-2 else float(t[1] - t[0])
    t_us = t * 1e6 if t[-1] < 1e-2 else t

    xs = (np.arange(grid) + 0.5) * DX - W_MM / 2
    zs = (np.arange(grid) + 0.5) * DZ
    X, Z = np.meshgrid(xs, zs)                      # (grid, grid)

    acc = np.zeros((grid, grid), dtype=np.float64)
    for k in range(n):
        xk, zk = positions[k]
        d = np.sqrt((X - xk) ** 2 + (Z - zk) ** 2)   # mm
        tau = 2.0 * d / C_TISSUE                     # us
        idx = tau / dt_us
        i0 = np.floor(idx).astype(np.int64)
        frac = idx - i0
        ok = (i0 >= 0) & (i0 < len(t_us) - 1)
        i0c = np.clip(i0, 0, len(t_us) - 2)
        v = rfs[k][i0c] * (1 - frac) + rfs[k][i0c + 1] * frac
        acc += np.where(ok, v, 0.0)
    return acc / n


def envelope(img_rf):
    from scipy.signal import hilbert
    env = np.abs(hilbert(img_rf, axis=0))
    return env


def to_bmode(env, dynamic_db=60.0):
    e = 20 * np.log10(env + 1e-12)
    lo = np.percentile(e, 5)
    e = np.clip(e - lo, 0, dynamic_db) / dynamic_db
    return e.astype(np.float32)


def mask_to_volume(mask, a_ratio=1.14):
    """掩膜 -> 椭球容积(mL)。边界点 PCA 求主轴，投影极值即半轴。

    返回 (volume_ml, truncated)。truncated=True 表示膀胱被视场边界截断，
    此时容积只能作为下限，应提示"超出视场，建议扩大扫查范围"。
    """
    m = mask.astype(bool)
    if m.sum() < 20:
        return 0.0, True
    ys, xs = np.nonzero(m)
    trunc = ((ys.max() >= MASK_N - 1) or (xs.max() >= MASK_N - 1)
             or (ys.min() <= 0) or (xs.min() <= 0))
    b = np.zeros_like(m)
    b[1:-1, 1:-1] = m[1:-1, 1:-1] & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])
    by, bx = np.nonzero(b)
    if len(bx) < 12:
        return 0.0, True
    x = bx * PIX_X
    y = by * PIX_Z
    pts = np.stack([x - x.mean(), y - y.mean()], axis=1)
    evals, evecs = np.linalg.eigh(np.cov(pts.T))
    u = evecs[:, int(np.argmax(evals))]
    v = evecs[:, int(np.argmin(evals))]
    a = float(np.percentile(np.abs(pts @ u), 99.5))
    c = float(np.percentile(np.abs(pts @ v), 99.5))
    bb = a_ratio * a
    return (4.0 / 3.0) * math.pi * a * bb * c / 1000.0, bool(trunc)


def segment(img128, ckpt=None):
    """U-Net 推理：128x128 B-mode → 64x64 概率图。"""
    import torch
    from unet_lite import UNetLite
    ckpt = ckpt or os.path.join(ROOT, "data", "unet_ckpt", "best.pt")
    m = UNetLite()
    m.load_state_dict(torch.load(ckpt, map_location="cpu"))
    m.eval()
    x = torch.from_numpy(img128[None, None].astype(np.float32))
    with torch.no_grad():
        p = torch.sigmoid(m(x))[0, 0].numpy()
    return p


def run_npz(path):
    d = np.load(path, allow_pickle=True)
    rf = d["rf"]
    t = d["t"]
    if rf.ndim == 1:
        rf = rf[None, :]
    t_us = (t * 1e6).astype(np.float64) if t[-1] < 1e-2 else t.astype(np.float64)
    rf_g = np.stack([tgc(rf[k], t_us) for k in range(rf.shape[0])])
    img_rf = das_image(rf_g, t_us if t[-1] >= 1e-2 else t_us)
    env = envelope(img_rf)
    bmode = to_bmode(env)
    prob = segment(bmode)
    mask = (prob > 0.5).astype(np.uint8)
    vol, trunc = mask_to_volume(mask)
    return dict(bmode=bmode, prob=prob, mask=mask, volume_ml=vol, truncated=trunc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        import torch
        from unet_lite import UNetLite
        x = np.load(os.path.join(ROOT, "data", "unet", "val", "imgs.npy"))[:4]
        m = np.load(os.path.join(ROOT, "data", "unet", "val", "masks.npy"))[:4]
        net = UNetLite(); net.load_state_dict(torch.load(os.path.join(ROOT, "data", "unet_ckpt", "best.pt")))
        net.eval()
        with torch.no_grad():
            p = torch.sigmoid(net(torch.from_numpy(x))).numpy()
        for i in range(4):
            vol, tr = mask_to_volume(p[i, 0] > 0.5)
            print(f"case{i}: pred_vol={vol:7.1f} mL  trunc={tr}")
        return
    if a.npz:
        r = run_npz(a.npz)
        print(f"volume = {r['volume_ml']:.1f} mL   truncated={r['truncated']}")
        np.save(os.path.join(ROOT, "data", "pipeline_out.npz"),
                bmode=r["bmode"], prob=r["prob"], mask=r["mask"])
        print("saved -> data/pipeline_out.npz")


if __name__ == "__main__":
    main()
