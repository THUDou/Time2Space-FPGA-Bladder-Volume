import os, sys, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))
from host_monitor import sphere_fit

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
d = np.load(os.path.join(OUT, "bladder_pulsed_dataset.npz"), allow_pickle=True)
rf, tofs, truths = d["rf"], d["tofs"], [json.loads(t) for t in d["truth"]]
PITCH = float(d["pitch"]); C_URINE = 1520.0

def t_wall(tr):
    return 0.0015/1620.0 + (tr["fat_cm"]/100)/1450.0 + (tr["muscle_cm"]/100)/1580.0

rows, errs = [], []
for i, tr in enumerate(truths):
    tw = t_wall(tr); pts = []
    for k in range(9):
        tf = tofs[i, k, 0]
        if tf == tf:
            dx, dy = (k % 3 - 1)*PITCH, (k//3 - 1)*PITCH
            zf = tr["z_wall"] + (tf/2 - tw)*C_URINE
            pts.append([dx, dy, zf])
    if len(pts) < 4:
        rows.append((tr["volume_ml"], len(pts), None, None)); continue
    try:
        c, r, vol = sphere_fit(np.array(pts))
        est = vol*1e6
        err = abs(est-tr["volume_ml"])/tr["volume_ml"]*100
        errs.append(err)
        rows.append((tr["volume_ml"], len(pts), round(est, 1), round(err, 1)))
    except Exception as e:
        rows.append((tr["volume_ml"], len(pts), "fit-fail", None))

print("volume_ml | hit_ch | est_ml | err%")
for r in rows:
    print(r)
if errs:
    print(f"\nsphere-fit MAPE = {np.mean(errs):.1f}%  median = {np.median(errs):.1f}%  n={len(errs)}")
print("注：sphere_fit 为正球近似（保守下限）；项目的椭球/几何先验+NN 轨会显著更准。")
