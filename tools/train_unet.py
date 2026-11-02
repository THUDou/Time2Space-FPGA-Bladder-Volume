import os, sys, json, time, argparse, math
sys.path.insert(0, "E:/sim_env")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from unet_lite import UNetLite, count_params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "unet")
CKPT = os.path.join(ROOT, "data", "unet_ckpt")
W_MM, D_MM = 80.0, 140.0
MASK_H = MASK_W = 64
PIX_X = W_MM / MASK_W
PIX_Z = D_MM / MASK_H

def load_split(split):
    d = os.path.join(DATA, split)
    imgs = np.load(os.path.join(d, "imgs.npy")).astype(np.float32)
    masks = np.load(os.path.join(d, "masks.npy")).astype(np.float32)
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    return imgs, masks, meta

def augment(x, y, gen):
    if gen.random() < 0.5:
        x = x * gen.uniform(0.75, 1.3) + gen.uniform(-0.05, 0.05)
        x = np.clip(x, 0, 1)
    if gen.random() < 0.3:
        x = np.clip(x ** gen.uniform(0.8, 1.25), 0, 1)
    if gen.random() < 0.5:
        x = np.clip(x + gen.normal(0, 0.02, x.shape).astype(np.float32), 0, 1)
    if gen.random() < 0.5:
        x = x[:, ::-1]
        y = y[:, ::-1]
    return np.ascontiguousarray(x), np.ascontiguousarray(y)

def dice_loss(logit, target, eps=1.0):
    p = torch.sigmoid(logit)
    num = 2 * (p * target).sum(dim=(2, 3)) + eps
    den = p.sum(dim=(2, 3)) + target.sum(dim=(2, 3)) + eps
    return 1 - (num / den).mean()

def iou_dice(pred, target):
    pred = pred > 0.5
    target = target > 0.5
    inter = (pred & target).sum(dim=(2, 3)).float()
    union = (pred | target).sum(dim=(2, 3)).float()
    iou = ((inter + 1e-6) / (union + 1e-6)).mean().item()
    dice = (2 * inter + 1e-6) / (pred.sum(dim=(2, 3)) + target.sum(dim=(2, 3)) + 1e-6)
    return iou, dice.mean().item()

def volume_from_mask(mask, a_ratio=1.14):
    m = mask.astype(bool)
    if m.sum() < 20:
        return 0.0, True
    ys, xs = np.nonzero(m)
    truncated = (ys.max() >= MASK_H - 1) or (xs.max() >= MASK_W - 1) or (ys.min() <= 0) or (xs.min() <= 0)
    cx, cz = xs.mean(), ys.mean()
    a = math.sqrt(max(((xs - cx) ** 2).mean(), 1e-6)) * math.sqrt(5.0)
    c = math.sqrt(max(((ys - cz) ** 2).mean(), 1e-6)) * math.sqrt(5.0)
    a_mm = a * PIX_X
    c_mm = c * PIX_Z
    b_mm = a_ratio * a_mm
    vol = (4.0 / 3.0) * math.pi * a_mm * b_mm * c_mm / 1000.0
    return vol, bool(truncated)

def evaluate(model, imgs, masks, metas, bs=16):
    model.eval()
    ious, dices, errs = [], [], []
    with torch.no_grad():
        for i in range(0, len(imgs), bs):
            x = torch.from_numpy(imgs[i:i + bs])
            y = torch.from_numpy(masks[i:i + bs])
            p = torch.sigmoid(model(x))
            iou, dice = iou_dice(p, y)
            ious.append(iou); dices.append(dice)
            for j in range(p.shape[0]):
                vol, trunc = volume_from_mask((p[j, 0].numpy() > 0.5))
                vt = metas[i + j]["volume_ml"]
                errs.append((vt, vol, trunc))
    errs_arr = np.array([(v, e) for v, e, t in errs])
    mape_all = float(np.mean(np.abs(errs_arr[:, 1] - errs_arr[:, 0]) / errs_arr[:, 0]) * 100)
    nt = np.array([(v, e) for v, e, t in errs if not t])
    mape_nt = float(np.mean(np.abs(nt[:, 1] - nt[:, 0]) / nt[:, 0]) * 100) if len(nt) else float("nan")
    return dict(dice=float(np.mean(dices)), iou=float(np.mean(ious)),
                vol_mape_all=mape_all, vol_mape_infov=mape_nt,
                frac_truncated=float(np.mean([t for _, _, t in errs])))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=18)
    ap.add_argument("--train", type=int, default=1500)
    ap.add_argument("--val", type=int, default=300)
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--mode", default="nearest")
    a = ap.parse_args()

    torch.set_num_threads(max(4, os.cpu_count() // 2))
    xtr, ytr, mtr = load_split("train")
    xva, yva, mva = load_split("val")
    xtr, ytr, mtr = xtr[:a.train], ytr[:a.train], mtr["params"][:a.train]
    xva, yva, mva = xva[:a.val], yva[:a.val], mva["params"][:a.val]
    print(f"train {len(xtr)}  val {len(xva)}  threads {torch.get_num_threads()}")

    model = UNetLite(mode=a.mode)
    print("params", count_params(model))
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs, eta_min=a.lr * 0.05)

    os.makedirs(CKPT, exist_ok=True)
    gen = np.random.default_rng(0)
    best = -1.0
    hist = []
    for ep in range(1, a.epochs + 1):
        model.train()
        idx = gen.permutation(len(xtr))
        tot, nb = 0.0, 0
        t0 = time.time()
        for i in range(0, len(idx), a.bs):
            bidx = idx[i:i + a.bs]
            xb = np.empty((len(bidx), 1, 128, 128), dtype=np.float32)
            yb = np.empty((len(bidx), 1, 64, 64), dtype=np.float32)
            for k, j in enumerate(bidx):
                xx, yy = augment(xtr[j, 0], ytr[j, 0], gen)
                xb[k, 0] = xx; yb[k, 0] = yy
            x = torch.from_numpy(xb); y = torch.from_numpy(yb)
            logit = model(x)
            loss = F.binary_cross_entropy_with_logits(logit, y) + dice_loss(logit, y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item(); nb += 1
        sched.step()
        ev = evaluate(model, xva, yva, mva)
        hist.append(dict(epoch=ep, loss=tot / nb, **ev))
        print(f"ep{ep:02d} loss={tot/nb:.4f} dice={ev['dice']:.4f} iou={ev['iou']:.4f} "
              f"MAPE_all={ev['vol_mape_all']:.1f}% MAPE_infov={ev['vol_mape_infov']:.1f}% "
              f"trunc={ev['frac_truncated']*100:.0f}% ({time.time()-t0:.0f}s)", flush=True)
        if ev["dice"] > best:
            best = ev["dice"]
            torch.save(model.state_dict(), os.path.join(CKPT, "best.pt"))
    with open(os.path.join(CKPT, "history.json"), "w", encoding="utf-8") as f:
        json.dump(dict(params=vars(a), history=hist, best_dice=best), f, ensure_ascii=False, indent=1)
    print("BEST_DICE", round(best, 4), "->", os.path.join(CKPT, "best.pt"))

if __name__ == "__main__":
    main()
