import os, json, math
import numpy as np

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(20260802)

TISSUE = {
    "skin":   dict(c=1620.0, rho=1109.0, alpha=2.0),
    "fat":    dict(c=1450.0, rho=952.0,  alpha=0.6),
    "muscle": dict(c=1580.0, rho=1050.0, alpha=1.0),
    "wall":   dict(c=1560.0, rho=1040.0, alpha=0.8),
    "urine":  dict(c=1520.0, rho=1000.0, alpha=0.1),
}
def Z(k): return TISSUE[k]["rho"] * TISSUE[k]["c"]
def Rcoef(k1, k2): return (Z(k2) - Z(k1)) / (Z(k2) + Z(k1))

FC = 3.5e6
FS = 25e6
N = 4096
DT = 1.0 / FS
CYCLES = 12
PITCH = 0.025
GAIN = 12.0

def bladder_shape(volume_ml, variant):
    V = volume_ml * 1e-6
    shape_k = 0.62 + 0.05 * variant["asym"]
    base = (V / (4.0/3.0*math.pi*shape_k)) ** (1.0/3.0)
    a = base * (0.86 + 0.10*variant["a_bias"])
    b = base * (0.80 + 0.10*variant["b_bias"])
    c = base * (1.18 + 0.15*variant["c_bias"])
    flatten = 0.10 + 0.06*variant["flatten"]
    return a, b, c, shape_k, flatten

def front_back_depth(x, y, cx, cy, cz, a, b, c, flatten):
    nx, ny = (x - cx)/a, (y - cy)/b
    r2 = nx*nx + ny*ny
    if r2 >= 1.0:
        return None
    sag = math.sqrt(1.0 - r2)
    z_front = cz - c*sag
    z_back  = cz + c*sag
    z_front += flatten * c * (1.0 - r2)
    return z_front, z_back

def burst_envelope(t_center, amp, t):
    dur = CYCLES / FC
    sigma = dur / 3.0
    env = amp * np.exp(-0.5*((t - t_center)/sigma)**2)
    return env * np.sin(2*np.pi*FC*(t - t_center))

def simulate_channel(x, y, wall_layers, bladder, noise_std):
    cz = bladder["cz"]; a,b,c,flatten = bladder["a"],bladder["b"],bladder["c"],bladder["flatten"]
    cx, cy = bladder["cx"], bladder["cy"]
    z_wall = sum(th for _, th in wall_layers)
    t = np.arange(N) * DT
    rf = np.zeros(N)
    events = []

    t_wall = sum(th / TISSUE[name]["c"] for name, th in wall_layers)
    def atten(extra_cm=0.0, key="urine"):
        dB = sum(TISSUE[name]["alpha"]*(FC/1e6)*(th*100.0) for name, th in wall_layers)*2.0
        dB += TISSUE[key]["alpha"]*(FC/1e6)*extra_cm*2.0
        return 10**(-dB/20.0)

    z_acc = 0.0
    for i in range(len(wall_layers)-1):
        z_acc += wall_layers[i][1]
        k1, k2 = wall_layers[i][0], wall_layers[i+1][0]
        tt = 2.0 * sum(th/TISSUE[n]["c"] for n, th in wall_layers[:i+1])
        if tt < N*DT:
            rf += burst_envelope(tt, abs(Rcoef(k1,k2))*atten()*0.6*GAIN, t)

    fb = front_back_depth(x, y, cx, cy, cz, a, b, c, flatten)
    tof_f = tof_b = None
    if fb is not None:
        zf, zb = fb
        tof_f = 2.0*(t_wall + max(zf - z_wall, 0)/TISSUE["urine"]["c"])
        amp_f = abs(Rcoef("muscle","urine"))*atten(max(zf-z_wall,0)*100)*0.9*GAIN
        tof_b = 2.0*(t_wall + max(zb - z_wall, 0)/TISSUE["urine"]["c"])
        amp_b = abs(Rcoef("urine","muscle"))*atten(max(zb-z_wall,0)*100)*0.9*GAIN
        if tof_f < N*DT: rf += burst_envelope(tof_f, amp_f, t)
        if tof_b < N*DT: rf += burst_envelope(tof_b, amp_b, t)
        events = [("front", tof_f, amp_f), ("back", tof_b, amp_b)]
    rf += rng.normal(0, noise_std, N) + rng.normal(0, noise_std*0.3, N)*np.sin(2*np.pi*FC*t)
    rf_code = np.clip(np.round(512 + rf*512), 0, 1023).astype(np.int16)
    return rf_code, tof_f, tof_b

def make_case(volume_ml, fat_cm, muscle_cm, variant):
    wall_layers = [("skin", 0.0015), ("fat", fat_cm/100.0), ("muscle", muscle_cm/100.0)]
    a,b,c,shape_k,flatten = bladder_shape(volume_ml, variant)
    z_wall = 0.0015 + fat_cm/100.0 + muscle_cm/100.0
    cz = z_wall + c + 0.004 + variant["gap"]
    bladder = dict(a=a,b=b,c=c,cz=cz,cx=variant["cx"],cy=variant["cy"],flatten=flatten)
    rfs = np.zeros((9, N), dtype=np.int16)
    tofs = np.zeros((9,2))
    for k in range(9):
        dx, dy = (k%3-1)*PITCH, (k//3-1)*PITCH
        rf, tf, tb = simulate_channel(dx, dy, wall_layers, bladder, variant["noise"])
        rfs[k] = rf
        tofs[k] = [tf if tf else np.nan, tb if tb else np.nan]
    truth = dict(volume_ml=volume_ml, fat_cm=fat_cm, muscle_cm=muscle_cm,
                 a=a,b=b,c=c,cz=cz,shape_k=shape_k, z_wall=z_wall)
    return rfs, tofs, truth

def main():
    volumes = [50,100,150,200,250,300,350,400]
    all_rfs, all_tofs, truths = [], [], []
    rows = []
    case_id = 0
    for vi, V in enumerate(volumes):
        for rep in range(2):
            variant = dict(a_bias=rng.uniform(-1,1), b_bias=rng.uniform(-1,1),
                           c_bias=rng.uniform(-1,1), asym=rng.uniform(-1,1),
                           flatten=rng.uniform(0,1), cx=rng.uniform(-0.004,0.004),
                           cy=rng.uniform(-0.004,0.004), gap=rng.uniform(0.0,0.01),
                           noise=rng.uniform(0.003,0.006))
            fat_cm = float(rng.uniform(0.5, 2.0))
            muscle_cm = float(rng.uniform(0.8, 1.6))
            rfs, tofs, truth = make_case(V, fat_cm, muscle_cm, variant)
            all_rfs.append(rfs); all_tofs.append(tofs); truths.append(truth)
            for k in range(9):
                rows.append(dict(case=case_id, ch=k, volume_ml=V, fat_cm=round(fat_cm,2),
                                 tof_front_us=tofs[k,0]*1e6 if tofs[k,0]==tofs[k,0] else "",
                                 tof_back_us=tofs[k,1]*1e6 if tofs[k,1]==tofs[k,1] else "",
                                 hit=bool(tofs[k,0]==tofs[k,0])))
            case_id += 1
    all_rfs = np.array(all_rfs); all_tofs = np.array(all_tofs)

    np.savez(os.path.join(OUT, "bladder_pulsed_dataset.npz"),
             rf=all_rfs, tofs=all_tofs,
             truth=np.array([json.dumps(t) for t in truths]),
             fs=FS, fc=FC, pitch=PITCH)
    import csv
    with open(os.path.join(OUT,"bladder_pulsed_features.csv"),"w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    est = []
    for i, truth in enumerate(truths):
        tf, tb = all_tofs[i,4,0], all_tofs[i,4,1]
        if tf==tf and tb==tb:
            dz = (tb-tf)*TISSUE["urine"]["c"]/2.0
            est.append((truth["volume_ml"], round(dz,5), round(truth["c"],5)))
    with open(os.path.join(OUT,"bladder_pulsed_geometry_check.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["volume_ml","dz_center_m","c_true_m"]); w.writerows(est)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(3,3, figsize=(13,8), sharex=True)
        for k in range(9):
            ax = axes[k//3, k%3]
            ax.plot(np.arange(N)*DT*1e6, all_rfs[8,k], lw=0.6)
            ax.set_title(f"CH{k} (V=250mL)", fontsize=8); ax.set_xlabel("us"); ax.grid(alpha=.3)
        fig.suptitle("9-channel pulse-echo RF (layered wall + non-ellipsoid bladder)")
        fig.tight_layout(); fig.savefig(os.path.join(OUT,"sim_rf_9ch.png"), dpi=130)

        t9 = truths[8]
        fig2, ax2 = plt.subplots(figsize=(6,6))
        th = np.linspace(0,2*np.pi,200)
        ax2.plot(t9["a"]*np.cos(th)*1000, t9["c"]*np.sin(th)*1000+t9["cz"]*1000, label="bladder(non-ellipsoid)")
        for k in range(9):
            dx,dy=(k%3-1)*PITCH,(k//3-1)*PITCH
            ax2.plot([dx*1000,dx*1000],[0,(t9["cz"])*1000],':',lw=0.5,color='gray')
        ax2.axhline(t9["z_wall"]*1000,color='r',ls='--',label="wall bottom")
        ax2.set_xlabel("x (mm)"); ax2.set_ylabel("z (mm)"); ax2.invert_yaxis()
        ax2.legend(); ax2.set_title("geometry cross-section"); ax2.grid(alpha=.3)
        fig2.tight_layout(); fig2.savefig(os.path.join(OUT,"sim_geometry.png"), dpi=130)
    except Exception as e:
        print("plot skipped:", e)

    print(f"cases={len(all_rfs)}  rf shape={all_rfs.shape}  -> {OUT}")
    print("files: bladder_pulsed_dataset.npz / _features.csv / _geometry_check.csv / sim_rf_9ch.png / sim_geometry.png")
    hit = (~np.isnan(all_tofs[:,:,0])).mean()
    print(f"front-wall hit ratio across all channels/cases: {hit:.2f}")

if __name__ == "__main__":
    main()
