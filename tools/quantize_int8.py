import os, sys, json, math
sys.path.insert(0, "E:/sim_env")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import torch
import torch.nn as nn
from unet_lite import UNetLite

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CKPT = os.path.join(ROOT, "data", "unet_ckpt", "best.pt")
MASK_N = 64
PIX_X, PIX_Z = 80.0 / 64, 140.0 / 64

def qsym(t, nbits=8):
    qmax = 2 ** (nbits - 1) - 1
    scale = t.abs().max() / qmax
    if scale <= 0:
        return t
    return torch.round(t / scale).clamp(-qmax - 1, qmax) * scale

def volume_from_mask(mask):
    m = np.asarray(mask, dtype=bool)
    if m.sum() < 20:
        return 0.0, True
    ys, xs = np.nonzero(m)
    trunc = (ys.max() >= MASK_N - 1) or (xs.max() >= MASK_N - 1) or (ys.min() <= 0) or (xs.min() <= 0)
    b = np.zeros_like(m)
    b[1:-1, 1:-1] = m[1:-1, 1:-1] & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])
    by, bx = np.nonzero(b)
    if len(bx) < 12:
        return 0.0, True
    x = bx * PIX_X
    y = by * PIX_Z
    pts = np.stack([x - x.mean(), y - y.mean()], axis=1)
    ev, evec = np.linalg.eigh(np.cov(pts.T))
    u = evec[:, int(np.argmax(ev))]
    v = evec[:, int(np.argmin(ev))]
    a = float(np.percentile(np.abs(pts @ u), 99.5))
    c = float(np.percentile(np.abs(pts @ v), 99.5))
    return (4.0 / 3.0) * math.pi * a * (1.14 * a) * c / 1000.0, bool(trunc)

def collect_act_max(model, x_cal):
    acts = {}
    hooks = []

    def mk(name):
        def f(mod, inp, out):
            acts[name] = max(acts.get(name, 0.0), float(out.abs().max()))
        return f

    for name, mod in model.named_modules():
        if isinstance(mod, nn.ReLU):
            hooks.append(mod.register_forward_hook(mk(name)))
    with torch.no_grad():
        model(x_cal)
    for h in hooks:
        h.remove()
    return acts

def quantize_model(model, acts, nbits=8):
    qmax = 2 ** (nbits - 1) - 1
    for mod in model.modules():
        if isinstance(mod, nn.Conv2d):
            w = mod.weight.data
            scale = w.abs().amax(dim=(1, 2, 3), keepdim=True) / qmax
            scale[scale == 0] = 1.0
            mod.weight.data = torch.round(w / scale).clamp(-qmax - 1, qmax) * scale

    hooks = []

    def mk(name):
        s = acts.get(name, 1.0) / qmax

        def f(mod, inp, out):
            if s <= 0:
                return out
            return torch.round(out / s).clamp(0, qmax) * s
        return f

    for name, mod in model.named_modules():
        if isinstance(mod, nn.ReLU):
            hooks.append(mod.register_forward_hook(mk(name)))
    return hooks

def evaluate(model, x, y, metas):
    with torch.no_grad():
        p = torch.sigmoid(model(x)).numpy()[:, 0]
    y = y.numpy()
    inter = ((p > 0.5) & (y[:, 0] > 0.5)).sum(axis=(1, 2))
    union = ((p > 0.5) | (y[:, 0] > 0.5)).sum(axis=(1, 2))
    iou = float(np.mean((inter + 1e-6) / (union + 1e-6)))
    dice = float(np.mean((2 * inter + 1e-6) / ((p > 0.5).sum(axis=(1, 2)) + (y[:, 0] > 0.5).sum(axis=(1, 2)) + 1e-6)))
    errs = []
    for i in range(len(p)):
        vol, tr = volume_from_mask(p[i] > 0.5)
        errs.append((metas[i]["volume_ml"], vol, tr))
    e = np.array([(a, b) for a, b, _ in errs])
    mape_all = float(np.mean(np.abs(e[:, 1] - e[:, 0]) / e[:, 0]) * 100)
    ok = np.array([(a, b) for a, b, t in errs if not t])
    mape_ok = float(np.mean(np.abs(ok[:, 1] - ok[:, 0]) / ok[:, 0]) * 100) if len(ok) else float("nan")
    return dict(dice=dice, iou=iou, mape_all=mape_all, mape_infov=mape_ok)

def main():
    imgs = np.load(os.path.join(ROOT, "data", "unet", "val", "imgs.npy"))[:200].astype(np.float32)
    masks = np.load(os.path.join(ROOT, "data", "unet", "val", "masks.npy"))[:200].astype(np.float32)
    metas = json.load(open(os.path.join(ROOT, "data", "unet", "val", "meta.json"), encoding="utf-8"))["params"][:200]

    net = UNetLite()
    net.load_state_dict(torch.load(CKPT, map_location="cpu"))
    net.eval()

    x = torch.from_numpy(imgs)
    y = torch.from_numpy(masks)

    r32 = evaluate(net, x, y, metas)
    print("FP32 :", {k: round(v, 4) if isinstance(v, float) else v for k, v in r32.items()})

    acts = collect_act_max(net, x[:64])
    hooks = quantize_model(net, acts, nbits=8)
    r8 = evaluate(net, x, y, metas)
    for h in hooks:
        h.remove()
    print("INT8 :", {k: round(v, 4) if isinstance(v, float) else v for k, v in r8.items()})

    nparam = sum(p.numel() for p in net.parameters())
    rep = dict(fp32=r32, int8=r8,
               params=nparam,
               weight_bytes_fp32=nparam * 4,
               weight_bytes_int8=nparam,
               act_layers=len(acts),
               drop_dice=round(r32["dice"] - r8["dice"], 4),
               drop_mape_infov=round(r8["mape_infov"] - r32["mape_infov"], 2))
    out = os.path.join(ROOT, "data", "hls4ml", "quant_int8_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("DICE 掉点:", rep["drop_dice"], " 容积MAPE变化:", rep["drop_mape_infov"], "pt")
    print("权重体积: %.1f KB -> %.1f KB" % (rep["weight_bytes_fp32"] / 1024, rep["weight_bytes_int8"] / 1024))
    print("saved ->", out)

if __name__ == "__main__":
    main()
