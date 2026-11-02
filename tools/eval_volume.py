import os, sys, json, math
sys.path.insert(0, "E:/sim_env")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import torch
from unet_lite import UNetLite

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W_MM, D_MM = 80.0, 140.0
N = 64
PX, PZ = W_MM / N, D_MM / N

def moments_axes(m):
    ys, xs = np.nonzero(m)
    if len(xs) < 20:
        return 0.0, 0.0
    a_px = 2.0 * np.sqrt(max(xs.var(), 1e-6))
    c_px = 2.0 * np.sqrt(max(ys.var(), 1e-6))
    return a_px * PX, c_px * PZ

def boundary_points(m):
    b = np.zeros_like(m, dtype=bool)
    b[1:-1, 1:-1] = m[1:-1, 1:-1] & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])
    ys, xs = np.nonzero(b)
    return xs.astype(float) * PX, ys.astype(float) * PZ

def fit_ellipse(x, y):
    if len(x) < 12:
        return 0.0, 0.0
    pts = np.stack([x - x.mean(), y - y.mean()], axis=1)
    cov = np.cov(pts.T)
    evals, evecs = np.linalg.eigh(cov)
    u, v = evecs[:, np.argmax(evals)], evecs[:, np.argmin(evals)]
    pu = np.abs(pts @ u)
    pv = np.abs(pts @ v)
    a = np.percentile(pu, 99.5)
    c = np.percentile(pv, 99.5)
    return float(a), float(c)

def where_mask_center(m):
    ys, xs = np.nonzero(m)
    return xs.mean(), ys.mean()

def main():
    imgs = np.load(os.path.join(ROOT, "data", "unet", "val", "imgs.npy"))[:300].astype(np.float32)
    masks = np.load(os.path.join(ROOT, "data", "unet", "val", "masks.npy"))[:300].astype(np.float32)
    metas = json.load(open(os.path.join(ROOT, "data", "unet", "val", "meta.json"), encoding="utf-8"))["params"][:300]

    net = UNetLite()
    net.load_state_dict(torch.load(os.path.join(ROOT, "data", "unet_ckpt", "best.pt"), map_location="cpu"))
    net.eval()
    with torch.no_grad():
        prob = torch.sigmoid(net(torch.from_numpy(imgs))).numpy()[:, 0]

    rows = []
    for i in range(len(prob)):
        m = prob[i] > 0.5
        if m.sum() < 20:
            continue
        ys, xs = np.nonzero(m)
        trunc = (ys.max() >= N - 1) or (xs.max() >= N - 1) or (ys.min() <= 0) or (xs.min() <= 0)
        a1, c1 = moments_axes(m)
        bx, by = boundary_points(m)
        a2, c2 = fit_ellipse(bx, by)
        vt = metas[i]["volume_ml"]
        v1 = 4 / 3 * math.pi * a1 * (1.14 * a1) * c1 / 1000.0
        v2 = 4 / 3 * math.pi * a2 * (1.14 * a2) * c2 / 1000.0 if a2 > 0 and c2 > 0 else v1
        rows.append((vt, v1, v2, trunc))

    r = np.array(rows, dtype=float)
    def mape(v, sel):
        s = r[sel]
        return float(np.mean(np.abs(s[:, 1] - s[:, 0]) / s[:, 0]) * 100) if len(s) else float("nan")
    def mape2(v, sel):
        s = r[sel]
        return float(np.mean(np.abs(s[:, 2] - s[:, 0]) / s[:, 0]) * 100) if len(s) else float("nan")

    sel_all = np.ones(len(r), bool)
    sel_ok = r[:, 3] < 0.5
    print(f"样本 {len(r)}  截断 {int(r[:,3].sum())}")
    print(f"方法A(矩)   全部 {mape2(0, sel_all):5.1f}%   未截断 {mape2(0, sel_ok):5.1f}%")
    print(f"方法B(椭圆拟合) 全部 {mape(0, sel_all):5.1f}%   未截断 {mape(0, sel_ok):5.1f}%")
    for lo, hi in ((0, 100), (100, 300), (300, 600), (600, 1500)):
        s = sel_ok & (r[:, 0] >= lo) & (r[:, 0] < hi)
        if s.sum():
            print(f"  {lo}-{hi} mL: n={int(s.sum()):3d}  A={mape2(0,s):5.1f}%  B={mape(0,s):5.1f}%")

if __name__ == "__main__":
    main()
