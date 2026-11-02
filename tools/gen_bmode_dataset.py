import os, json, math
import numpy as np
from scipy.ndimage import convolve1d as scipy_conv1d

W_MM = 80.0
D_MM = 140.0
H, W = 128, 128
MASK_H, MASK_W = 64, 64
DX = W_MM / W
DZ = D_MM / H

TISSUE = {
    "skin":   (1540.0, 1100.0, 1.5),
    "fat":    (1470.0, 920.0,  0.5),
    "muscle": (1580.0, 1050.0, 1.0),
    "wall":   (1560.0, 1050.0, 0.8),
    "urine":  (1520.0, 1000.0, 0.002),
    "soft":   (1550.0, 1040.0, 0.7),
}
F0_MHZ = 3.5

def _maps(params):
    z = (np.arange(H)[:, None] + 0.5) * DZ
    x = (np.arange(W)[None, :] - W / 2 + 0.5) * DX

    c = np.full((H, W), TISSUE["soft"][0])
    rho = np.full((H, W), TISSUE["soft"][1])
    al = np.full((H, W), TISSUE["soft"][2])

    z1 = z[:, 0]
    z_skin = params["skin_mm"]
    z_fat = z_skin + params["fat_mm"]
    z_mus = z_fat + params["muscle_mm"]

    def put(cond, key):
        m = cond
        c[m] = TISSUE[key][0]
        rho[m] = TISSUE[key][1]
        al[m] = TISSUE[key][2]

    m_skin = np.broadcast_to((z1 < z_skin)[:, None], (H, W))
    m_fat = np.broadcast_to(((z1 >= z_skin) & (z1 < z_fat))[:, None], (H, W))
    m_mus = np.broadcast_to(((z1 >= z_fat) & (z1 < z_mus))[:, None], (H, W))
    put(m_skin, "skin"); put(m_fat, "fat"); put(m_mus, "muscle")

    a, b, cc = params["a"], params["b"], params["c"]
    zc = z_mus + 8.0 + params["c_ant"] + params["dz_off"]
    xc = params["dx_off"]
    th = math.radians(params["tilt"])

    X = (x - xc) * math.cos(th) + (z - zc) * math.sin(th)
    Z = -(x - xc) * math.sin(th) + (z - zc) * math.cos(th)
    c_eff = np.where(Z < 0, params["c_ant"], params["c_post"])
    n = params["n_exp"]
    r = np.abs(X / a) ** n + np.abs(Z / c_eff) ** n

    lumen = r < 1.0
    wall = (r >= 1.0) & (r < 1.0 + params["wall_th"] / max(a, 1e-3) * 1.0)
    put(wall, "wall"); put(lumen, "urine")
    return c, rho, al, lumen

SCATTER = {"skin": 1.2, "fat": 1.0, "muscle": 0.85, "wall": 0.9, "urine": 0.004, "soft": 0.9}

def synth_bmode(params, rng):
    c, rho, al, lumen = _maps(params)
    Z = rho * c

    dZ = np.abs(np.gradient(Z, axis=0))
    dZ = dZ / (Z + 1e-9)

    smap = np.full((H, W), SCATTER["soft"])
    z = (np.arange(H)[:, None] + 0.5) * DZ
    z1 = z[:, 0]
    z_skin = params["skin_mm"]; z_fat = z_skin + params["fat_mm"]
    z_mus = z_fat + params["muscle_mm"]
    smap[np.broadcast_to((z1 < z_skin)[:, None], (H, W))] = SCATTER["skin"]
    smap[np.broadcast_to(((z1 >= z_skin) & (z1 < z_fat))[:, None], (H, W))] = SCATTER["fat"]
    smap[np.broadcast_to(((z1 >= z_fat) & (z1 < z_mus))[:, None], (H, W))] = SCATTER["muscle"]
    smap[lumen] = SCATTER["urine"]

    path_cm = np.cumsum(np.full((H, 1), DZ / 10.0), axis=0)
    att_db = 2.0 * (al * F0_MHZ) * path_cm
    att = 10 ** (-att_db / 20.0)

    n1 = rng.normal(size=(H, W)) * smap
    n2 = rng.normal(size=(H, W)) * smap

    sig_z = 0.35 / DZ
    k = np.arange(-4, 5)
    g = np.exp(-(k ** 2) / (2 * sig_z ** 2)); g /= g.sum()

    z_mm = (np.arange(H) + 0.5) * DZ
    beam_mm = params["beam0_mm"] + params["beam_grow"] * z_mm
    sig_x = beam_mm / DX
    kk = np.arange(-12, 13)

    def psf(a):
        a = scipy_conv1d(a, g, axis=0)
        for i in range(H):
            s = max(sig_x[i], 0.35)
            gg = np.exp(-(kk ** 2) / (2 * s ** 2)); gg /= gg.sum()
            a[i] = np.convolve(a[i], gg, mode="same")
        return a

    n1 = psf(n1); n2 = psf(n2)
    speck_amp = np.sqrt(n1 ** 2 + n2 ** 2)
    speck_amp /= (np.percentile(speck_amp, 90) + 1e-12)

    struct = psf(dZ) * params["struct_gain"]
    img = (struct + speck_amp) * att

    tgc = (1.0 + z_mm / params["tgc_z0_mm"]) ** params["tgc_pow"]
    img = img * tgc[:, None] * params["gain"]

    eps = params["noise"] * (np.percentile(img, 99) + 1e-12)
    img = 20 * np.log10(np.abs(img) + eps + 1e-12)
    img = img - np.percentile(img, 1)
    rng_db = params["dynamic_db"]
    img = np.clip(img, 0, rng_db) / rng_db
    img = img + rng.normal(0, params["read_noise"], img.shape)
    img = np.clip(img, 0, 1).astype(np.float32)

    lm = lumen.astype(np.float32)
    m = lm.reshape(MASK_H, 2, MASK_W, 2).mean(axis=(1, 3))
    mask = (m > 0.5).astype(np.uint8)
    return img, mask

def sample_params(rng, extreme_p=0.12):
    if rng.random() < extreme_p:
        vol = float(rng.uniform(800.0, 1500.0))
    else:
        vol = float(np.exp(rng.uniform(np.log(20.0), np.log(600.0))))
    k = (3.0 * vol * 1e-6 / (4.0 * math.pi * 1.14 * 0.86)) ** (1.0 / 3.0) * 1000.0
    a, b, c = k, 1.14 * k, 0.86 * k
    c_ant = float(c * rng.uniform(0.65, 1.0))
    c_post = float(c * rng.uniform(1.0, 1.12))
    return dict(
        volume_ml=vol, a=float(a), b=float(b), c=float(c),
        c_ant=c_ant, c_post=c_post,
        skin_mm=float(rng.uniform(1.5, 2.5)),
        fat_mm=float(rng.uniform(10.0, 35.0)),
        muscle_mm=float(rng.uniform(6.0, 16.0)),
        dx_off=float(rng.uniform(-15.0, 15.0)),
        dz_off=float(rng.uniform(-12.0, 8.0)),
        tilt=float(rng.uniform(-12.0, 12.0)),
        n_exp=float(rng.uniform(2.0, 2.8)),
        wall_th=float(rng.uniform(2.0, 4.5)),
        beam0_mm=float(rng.uniform(1.6, 3.2)),
        beam_grow=float(rng.uniform(0.02, 0.06)),
        struct_gain=float(rng.uniform(0.25, 0.9)),
        tgc_z0_mm=float(rng.uniform(18.0, 34.0)),
        tgc_pow=float(rng.uniform(0.9, 1.5)),
        gain=float(rng.uniform(0.6, 1.8)),
        noise=float(rng.uniform(0.004, 0.03)),
        dynamic_db=float(rng.uniform(42.0, 66.0)),
        read_noise=float(rng.uniform(0.0, 0.02)),
    )

def build(n, seed, out_dir):
    rng = np.random.default_rng(seed)
    imgs = np.zeros((n, 1, H, W), dtype=np.float16)
    masks = np.zeros((n, 1, MASK_H, MASK_W), dtype=np.uint8)
    metas = []
    for i in range(n):
        p = sample_params(rng)
        img, mask = synth_bmode(p, rng)
        imgs[i, 0] = img
        masks[i, 0] = mask
        p["mask_area"] = int(mask.sum())
        metas.append(p)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{n}", flush=True)
    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "imgs.npy"), imgs)
    np.save(os.path.join(out_dir, "masks.npy"), masks)
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(dict(n=n, seed=seed, grid=dict(W_MM=W_MM, D_MM=D_MM, H=H, W=W,
                                                 MASK_H=MASK_H, MASK_W=MASK_W),
                       params=metas), f, ensure_ascii=False)
    print(f"saved {n} -> {out_dir}")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="data/unet/train")
    a = ap.parse_args()
    build(a.n, a.seed, a.out)
