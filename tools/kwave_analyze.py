import os, sys, json, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import hilbert, find_peaks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KW = os.path.join(ROOT, "data", "kwave")
C_URINE = 1520.0

def load_case(vol, row, col):
    f = os.path.join(KW, f"v{vol}_r{row}c{col}.npz")
    if not os.path.exists(f):
        for cand in glob.glob(os.path.join(KW, f"v{vol}*_r{row}c{col}.npz")):
            f = cand
            break
    if not os.path.exists(f):
        return None
    d = np.load(f, allow_pickle=True)
    return dict(rf=d["rf"].astype(np.float32), t=d["t"].astype(np.float32),
                dt=float(d["dt"]), meta=json.loads(str(d["meta"])), path=f)

def tgc(rf, t, t0=8e-6, power=2.0):
    g = np.clip(t / t0, 1.0, None) ** power
    out = rf.astype(float) * g
    out[t < t0] *= 0.02
    return out

def analyze(vol=200):
    cases = {}
    for row in range(3):
        for col in range(3):
            c = load_case(vol, row, col)
            if c:
                cases[(row, col)] = c
    if not cases:
        print("NO_DATA")
        return
    n = min(c["rf"].size for c in cases.values())
    rows = []
    print(f"loaded {len(cases)} channels, N={n}")
    for (row, col), c in sorted(cases.items()):
        rf = c["rf"][:n]
        t = c["t"][:n]
        y = tgc(rf, t)
        env = np.abs(hilbert(y))
        rows.append(env)
        m = c["meta"]
        ta = 2 * m["ant_depth"] / 1500.0
        tp = 2 * m["post_depth"] / 1500.0
        print(f"  r{row}c{col}: ant={m['ant_depth']*1e3:.1f}mm(t={ta*1e6:.1f}us) "
              f"post={m['post_depth']*1e3:.1f}mm(t={tp*1e6:.1f}us) "
              f"a_eff={m['a_eff']*1e3:.1f}mm env_max={env.max():.3g}")
    E = np.vstack(rows)
    rf9 = np.vstack([cases[k]["rf"][:n] for k in sorted(cases)])
    t = cases[sorted(cases)[0]]["t"][:n]

    out_npz = os.path.join(KW, f"bladder_kwave_9ch_{vol}ml.npz")
    np.savez_compressed(out_npz, rf=rf9, env=E.astype(np.float32), t=t,
                        ch_order=np.array([f"r{r}c{c}" for r, c in sorted(cases)]))
    print("SAVED", out_npz, rf9.shape)

    fig, axes = plt.subplots(3, 3, figsize=(13, 8), sharex=True, sharey=True)
    for ax, (k, e) in zip(axes.ravel(), zip(sorted(cases), E)):
        ax.plot(t * 1e6, e, lw=0.7, color="#c0392b")
        ax.set_title(f"row {k[0]}  col {k[1]}", fontsize=9)
        ax.grid(alpha=0.25)
    for ax in axes[-1]:
        ax.set_xlabel("time (us)")
    for ax in axes[:, 0]:
        ax.set_ylabel("TGC envelope")
    fig.suptitle(f"k-Wave 2D full-wave pulse-echo  9 channels  ({vol} mL bladder)", fontsize=12)
    fig.tight_layout()
    png = os.path.join(ROOT, "data", f"kwave_9ch_{vol}ml.png")
    fig.savefig(png, dpi=150)
    print("FIG", png)

if __name__ == "__main__":
    v = float(sys.argv[1]) if len(sys.argv) > 1 else 200.0
    analyze(v)
