import sys, os, json, time, argparse
sys.path.insert(0, "E:/sim_env")
import numpy as np

import kwave.utils.io as _kio
_orig_assign = _kio.assign_str_attr

def _assign_utf8(attrs, attr_name, attr_val):
    try:
        _orig_assign(attrs, attr_name, attr_val)
    except Exception:
        try:
            attrs.create(attr_name, str(attr_val).encode("utf-8", "replace"))
        except Exception:
            pass

_kio.assign_str_attr = _assign_utf8

from kwave.kgrid import kWaveGrid
from kwave.kmedium import kWaveMedium
from kwave.ksource import kSource
from kwave.ksensor import kSensor
from kwave.kspaceFirstOrder2D import kspaceFirstOrder2D
from kwave.options.simulation_options import SimulationOptions
from kwave.options.simulation_execution_options import SimulationExecutionOptions

F0 = 3.5e6
DX = 1.5e-4
R_CAP = 82e-3
PITCH = 25e-3
X_HALF = 40.5e-3
Z_MAX = 90e-3
PML = 20
DATA_DIR = "E:/kwave_data"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kwave")

TISSUE = {
    "skin":   dict(c=1540.0, rho=1100.0, a=1.5),
    "fat":    dict(c=1470.0, rho=920.0,  a=0.5),
    "muscle": dict(c=1580.0, rho=1050.0, a=1.0),
    "urine":  dict(c=1520.0, rho=1000.0, a=0.002),
    "wall":   dict(c=1560.0, rho=1050.0, a=0.8),
    "soft":   dict(c=1550.0, rho=1040.0, a=0.7),
}

def elem_positions(y_off):
    xs = [-PITCH, 0.0, PITCH]
    out = []
    for x in xs:
        r2 = x * x + y_off * y_off
        z = R_CAP - np.sqrt(max(R_CAP ** 2 - r2, 0.0))
        out.append((x, z - 0.0))
    return out

def bladder_axes(vol_ml, y_off):
    V = vol_ml * 1e-6
    k = (3.0 * V / (4.0 * np.pi * 1.14 * 0.86)) ** (1.0 / 3.0)
    a, b, c = k, 1.14 * k, 0.86 * k
    a_eff = a * np.sqrt(max(1.0 - (y_off / b) ** 2, 0.0))
    c_ant = 0.82 * c
    c_post = 1.08 * c
    zc = 22e-3 + c_ant
    return a_eff, c_ant, c_post, zc

def build_phantom(kgrid, vol_ml, y_off, fat_mm=20.0, tilt_deg=6.0):
    Nx, Ny = kgrid.Nx, kgrid.Ny
    Nz = Ny
    x = np.arange(Nx)[:, None] * DX - X_HALF
    z = np.arange(Nz)[None, :] * DX
    z1 = np.arange(Nz) * DX

    col_c = np.full(Nz, TISSUE["soft"]["c"])
    col_rho = np.full(Nz, TISSUE["soft"]["rho"])
    col_a = np.full(Nz, TISSUE["soft"]["a"])
    for key, z0, z1e in (("skin", 0.0, 2e-3),
                         ("fat", 2e-3, (2.0 + fat_mm) * 1e-3),
                         ("muscle", (2.0 + fat_mm) * 1e-3, (2.0 + fat_mm + 12.0) * 1e-3)):
        m = (z1 >= z0) & (z1 < z1e)
        col_c[m] = TISSUE[key]["c"]
        col_rho[m] = TISSUE[key]["rho"]
        col_a[m] = TISSUE[key]["a"]

    c = np.broadcast_to(col_c[None, :], (Nx, Nz)).copy()
    rho = np.broadcast_to(col_rho[None, :], (Nx, Nz)).copy()
    al = np.broadcast_to(col_a[None, :], (Nx, Nz)).copy()

    a_eff, c_ant, c_post, zc = bladder_axes(vol_ml, y_off)
    if a_eff <= 0:
        return c, rho, al, dict(volume_ml=vol_ml, y_off=y_off, a_eff=0.0, zc=zc,
                                c_ant=c_ant, c_post=c_post, in_plane=False)

    th = np.deg2rad(tilt_deg)
    X = x * np.cos(th) + (z - zc) * np.sin(th)
    Z = -x * np.sin(th) + (z - zc) * np.cos(th)
    c_eff = np.where(Z < 0, c_ant, c_post)
    N_EXP = 2.35
    r = (np.abs(X / a_eff) ** N_EXP + np.abs(Z / c_eff) ** N_EXP)
    m_urine = r < 1.0
    m_wall = (r >= 1.0) & (r < 1.13) & (z > 2e-3)

    c[m_wall] = TISSUE["wall"]["c"]; rho[m_wall] = TISSUE["wall"]["rho"]; al[m_wall] = TISSUE["wall"]["a"]
    c[m_urine] = TISSUE["urine"]["c"]; rho[m_urine] = TISSUE["urine"]["rho"]; al[m_urine] = TISSUE["urine"]["a"]

    meta = dict(volume_ml=vol_ml, y_off=y_off, a_eff=a_eff, zc=zc,
                c_ant=c_ant, c_post=c_post, in_plane=True,
                ant_depth=float(zc - c_ant), post_depth=float(zc + c_post),
                urine_px=int(m_urine.sum()))
    return c, rho, al, meta

def burst(t, n_cycles=3.0, f0=F0):
    t0 = 1.2 * n_cycles / f0
    env = np.exp(-((t - t0) ** 2) / (2.0 * (n_cycles / (2.2 * f0)) ** 2))
    return np.sin(2.0 * np.pi * f0 * (t - t0)) * env

def run_case(vol_ml, row, col, y_off, elem_dia=10e-3, quick=False, tag=None, verbose=True):
    dx = DX * (2 if quick else 1)
    Nx = int(round(2 * X_HALF / dx))
    Nz = int(round(Z_MAX / dx))
    kgrid = kWaveGrid([Nx, Nz], [dx, dx])

    c_map, rho_map, al_map, meta = build_phantom(kgrid, vol_ml, y_off)
    c_max = float(c_map.max())
    t_end = 2.0 * (Z_MAX - 2e-3) / TISSUE["urine"]["c"]
    if quick:
        t_end *= 0.6
    kgrid.makeTime(c_max, cfl=0.3, t_end=t_end)

    ex, ez = elem_positions(y_off)[col]
    ix = int(round((ex + X_HALF) / dx))
    iz = int(round(ez / dx))
    half = max(int(round(elem_dia / 2 / dx)), 1)

    ix = int(np.clip(ix, PML + half + 1, Nx - PML - half - 1))
    iz = int(np.clip(iz, PML + 1, Nz - PML - 2))

    src_mask = np.zeros((Nx, Nz), dtype=bool)
    src_mask[max(ix - half, 0):ix + half, iz] = True

    medium = kWaveMedium(sound_speed=c_map, density=rho_map,
                         alpha_coeff=al_map, alpha_power=1.1)

    source = kSource()
    source.p_mask = src_mask
    source.p = burst(kgrid.t_array).reshape(1, -1)

    sensor = kSensor()
    s_mask = np.zeros((Nx, Nz), dtype=bool)
    s_mask[ix, iz + 1] = True
    sensor.mask = s_mask
    sensor.record = ["p"]

    tag = tag or f"v{vol_ml}_r{row}c{col}" + ("_quick" if quick else "")
    os.makedirs(DATA_DIR, exist_ok=True)
    opts = SimulationOptions(save_to_disk=True, data_cast="single", pml_inside=True,
                             pml_size=PML, data_path=DATA_DIR + "/",
                             input_filename=f"in_{tag}.h5", output_filename=f"out_{tag}.h5")
    ex_opts = SimulationExecutionOptions(is_gpu_simulation=False, show_sim_log=False,
                                         verbose_level=0, delete_data=True)

    t0 = time.time()
    if verbose:
        print(f"[{tag}] grid {Nx}x{Nz} Nt={kgrid.Nt} c_max={c_max:.0f} "
              f"elem=({ex*1e3:.1f},{ez*1e3:.1f})mm urine_px={meta.get('urine_px')}", flush=True)
    out = kspaceFirstOrder2D(kgrid, source, sensor, medium, opts, ex_opts)
    p = np.asarray(out["p"]).reshape(-1)
    dt = float(kgrid.dt)
    tvec = np.arange(p.size) * dt

    os.makedirs(OUT_DIR, exist_ok=True)
    npz = os.path.join(OUT_DIR, f"{tag}.npz")
    np.savez_compressed(npz, rf=p.astype(np.float32), t=tvec.astype(np.float32),
                        dt=dt, f0=F0, dx=dx, meta=json.dumps(meta))
    if verbose:
        print(f"[{tag}] done {time.time()-t0:.0f}s -> {npz} rms={float(np.sqrt((p**2).mean())):.4g}", flush=True)
    return npz, p, tvec, meta

def run_all(vol_ml):
    from multiprocessing import Pool
    tasks = []
    for row, yoff_mm in enumerate((-25.0, 0.0, 25.0)):
        for col in range(3):
            tasks.append((vol_ml, row, col, yoff_mm * 1e-3))
    print("TASKS", len(tasks), flush=True)
    with Pool(processes=len(tasks)) as pool:
        res = pool.starmap(run_case, tasks)
    for r in res:
        print("OUT", r[0], flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vol", type=float, default=200.0)
    ap.add_argument("--row", type=int, default=1)
    ap.add_argument("--col", type=int, default=1)
    ap.add_argument("--yoff", type=float, default=0.0)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.all:
        run_all(a.vol)
    else:
        run_case(a.vol, a.row, a.col, a.yoff * 1e-3, quick=a.quick)

if __name__ == "__main__":
    main()
