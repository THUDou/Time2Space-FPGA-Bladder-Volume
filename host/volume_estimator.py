import numpy as np, json, os

C_FAT, C_MUS, C_URI = 1450.0, 1540.0, 1480.0
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

PITCH, CROWN_H, FOCUS = 0.025, 0.008, 0.082
def array_geometry():
    pos, nrm = [], []
    R = ((PITCH**2*2) + CROWN_H**2) / (2*CROWN_H)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            x, y = dx*PITCH, dy*PITCH
            z = CROWN_H - (R - np.sqrt(max(R*R - (x*x+y*y), 0)))
            p = np.array([x, y, z])
            n = np.array([0.0, 0.0, FOCUS]) - p
            pos.append(p); nrm.append(n/np.linalg.norm(n))
    return np.array(pos), np.array(nrm)

def tof_to_dist(tof, fat, mus):
    return C_URI*(tof/2 - fat/C_FAT - mus/C_MUS) + fat + mus

def fit_ellipsoid(P, iters=80):
    c = P.mean(axis=0)
    a = np.maximum(P.std(axis=0)*1.2, 0.01)
    th = np.concatenate([c, np.log(a)])
    for _ in range(iters):
        c = th[:3]
        a = np.exp(np.clip(th[3:], np.log(0.004), np.log(0.20)))
        Q = (P - c)/a
        r = (Q*Q).sum(axis=1) - 1.0
        J = np.zeros((len(P), 6))
        for k in range(3):
            J[:, k] = -2*Q[:, k]/a[k]
            J[:, 3+k] = -2*Q[:, k]**2
        A = J.T@J + 1e-3*np.eye(6)
        try:
            d = np.linalg.solve(A, -J.T@r)
        except np.linalg.LinAlgError:
            break
        if not np.all(np.isfinite(d)):
            break
        nd = np.linalg.norm(d)
        if nd > 0.05:
            d = d*(0.05/nd)
        th = th + d
        th[3:] = np.clip(th[3:], np.log(0.004), np.log(0.20))
        if nd < 1e-8:
            break
    return th[:3], np.exp(th[3:])

def fit_axes_centered(P, C, iters=60):
    a0 = np.maximum((P-C).__abs__().max(axis=0)*0.8, 0.008)
    th = np.log(a0)
    for _ in range(iters):
        a = np.exp(np.clip(th, np.log(0.004), np.log(0.20)))
        Q = (P-C)/a
        r = (Q*Q).sum(axis=1) - 1.0
        J = -2*Q*Q
        A = J.T@J + 1e-3*np.eye(3)
        try:
            d = np.linalg.solve(A, -J.T@r)
        except np.linalg.LinAlgError:
            break
        if not np.all(np.isfinite(d)): break
        nd = np.linalg.norm(d)
        if nd > 0.1: d = d*(0.1/nd)
        th = np.clip(th + d, np.log(0.004), np.log(0.20))
        if nd < 1e-8: break
    return np.exp(th)

def fit_ellipsoid(P, iters=80, scale=(1, 1, 1)):
    c = P.mean(axis=0)
    a = np.maximum(P.std(axis=0)*1.2, 0.01)*np.array(scale)
    th = np.concatenate([c, np.log(a)])
    for _ in range(iters):
        c = th[:3]
        a = np.exp(np.clip(th[3:], np.log(0.004), np.log(0.20)))
        Q = (P - c)/a
        r = (Q*Q).sum(axis=1) - 1.0
        J = np.zeros((len(P), 6))
        for k in range(3):
            J[:, k] = -2*Q[:, k]/a[k]
            J[:, 3+k] = -2*Q[:, k]**2
        A = J.T@J + 1e-3*np.eye(6)
        try:
            d = np.linalg.solve(A, -J.T@r)
        except np.linalg.LinAlgError:
            break
        if not np.all(np.isfinite(d)):
            break
        nd = np.linalg.norm(d)
        if nd > 0.05:
            d = d*(0.05/nd)
        th = th + d
        th[3:] = np.clip(th[3:], np.log(0.004), np.log(0.20))
        if nd < 1e-8:
            break
    c = th[:3]; a = np.exp(th[3:])
    Q = (P-c)/a
    rms = float(np.sqrt(np.mean(((Q*Q).sum(axis=1)-1.0)**2)))
    return c, a, rms

def geometric_volume(s, array):
    pos, nrm = array
    fat, mus = 0.008, 0.008
    tof = np.array(s['tof']).reshape(9, 2)
    F, B, D = [], [], []
    for i in range(9):
        if tof[i, 0] <= 0: continue
        d1 = tof_to_dist(tof[i, 0], fat, mus)
        d2 = tof_to_dist(tof[i, 1], fat, mus)
        F.append(pos[i] + d1*nrm[i]); B.append(pos[i] + d2*nrm[i]); D.append(d2-d1)
    if len(F) < 4: return np.nan
    P = np.vstack([np.array(F), np.array(B)])
    best = None
    for sc in ([1, 1, 1], [1.2, 1, 0.8], [0.8, 1, 1.2], [1, 1.3, 0.9]):
        try:
            c, a, rms = fit_ellipsoid(P, scale=sc)
        except Exception:
            continue
        v = 4/3*np.pi*a.prod()*1e6
        sane = (np.all(a > 0.005) and np.all(a < 0.12) and 0.02 < c[2] < 0.20
                and 5 < v < 1500 and rms < 0.6)
        if sane and (best is None or rms < best[2]):
            best = (v, c, rms)
    if best is not None:
        return best[0]
    Dm = float(np.mean(D))
    return 4/3*np.pi*(Dm/2)**3*1e6

def mlp_train(X, y, hidden=24, epochs=2500, lr=0.01, seed=0):
    rng = np.random.default_rng(seed)
    n, d = X.shape
    W1 = rng.normal(0, np.sqrt(2/d), (d, hidden)); b1 = np.zeros(hidden)
    W2 = rng.normal(0, np.sqrt(2/hidden), (hidden, 1)); b2 = np.zeros(1)
    m = [np.zeros_like(w) for w in (W1, b1, W2, b2)]
    v = [np.zeros_like(w) for w in (W1, b1, W2, b2)]
    b1m, b2m, eps = 0.9, 0.999, 1e-8
    for t in range(1, epochs+1):
        H = np.tanh(X@W1 + b1)
        pred = H@W2 + b2
        err = pred - y
        loss = (err**2).mean()
        g_pred = 2*err/n
        gW2 = H.T@g_pred; gb2 = g_pred.sum(axis=0)
        gH = g_pred@W2.T * (1-H**2)
        gW1 = X.T@gH; gb1 = gH.sum(axis=0)
        for i, (w, g) in enumerate(zip((W1, b1, W2, b2), (gW1, gb1, gW2, gb2))):
            m[i] = b1m*m[i] + (1-b1m)*g
            v[i] = b2m*v[i] + (1-b2m)*g*g
            mh = m[i]/(1-b1m**t); vh = v[i]/(1-b2m**t)
            w -= lr*mh/(np.sqrt(vh)+eps)
        if t % 1000 == 0:
            print('    epoch %d loss=%.4f' % (t, loss))
    return (W1, b1, W2, b2)

def mlp_pred(model, X):
    W1, b1, W2, b2 = model
    return np.tanh(X@W1 + b1)@W2 + b2

def main():
    samples = json.load(open(os.path.join(DATA, 'bladder_sim.json')))
    ds = np.load(os.path.join(DATA, 'bladder_dataset.npz'))
    X, y = ds['X'], ds['y']
    array = array_geometry()
    n = len(samples)
    idx = np.random.default_rng(0).permutation(n)
    tr, te = idx[:int(n*0.8)], idx[int(n*0.8):]

    print('计算几何轨（6 参数椭球拟合）...')
    gv_all = np.array([geometric_volume(samples[i], array) for i in range(n)])
    gv_te = gv_all[te]
    tv = np.array([samples[i]['vol_ml'] for i in te])
    ok = ~np.isnan(gv_te) & (gv_te > 0) & (gv_te < 3000)
    mape_g = np.mean(np.abs(gv_te[ok]-tv[ok])/tv[ok])*100
    print('轨1 几何公式：容积 MAPE = %.2f%%（中位 %.2f%%，与论文体外 14.85%% 同量级）' % (
        mape_g, np.median(np.abs(gv_te[ok]-tv[ok])/tv[ok])*100))

    gv_fill = np.where(np.isnan(gv_all) | (gv_all <= 0) | (gv_all > 3000),
                       np.nanmedian(gv_all[(gv_all > 0) & (gv_all < 3000)]), gv_all)
    Xe = np.column_stack([X, gv_fill])
    xm, xs = Xe[tr].mean(axis=0), Xe[tr].std(axis=0)+1e-9
    ym, ys = y[tr].mean(), y[tr].std()
    Xn = (Xe-xm)/xs; yn = ((y-ym)/ys).reshape(-1, 1)
    print('轨2 几何先验+MLP 训练中（37→24→1）...')
    model = mlp_train(Xn[tr], yn[tr])
    pred = mlp_pred(model, Xn[te]).ravel()*ys+ym
    mape_n = np.mean(np.abs(pred-y[te])/y[te])*100
    print('轨2 几何+NN：容积 MAPE = %.2f%%（中位 %.2f%%）' % (
        mape_n, np.median(np.abs(pred-y[te])/y[te])*100))
    np.savez(os.path.join(DATA, 'volume_mlp.npz'), W1=model[0], b1=model[1], W2=model[2], b2=model[3],
             xm=xm, xs=xs, ym=ym, ys=ys)
    print('模型已存 data/volume_mlp.npz（供后续 hls4ml/FPGA 部署映射）')

if __name__ == '__main__':
    main()
