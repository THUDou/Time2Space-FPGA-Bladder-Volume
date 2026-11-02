import random, math

C_WATER = 1480.0
F0      = 3.5e6
LAMBDA  = C_WATER / F0

def solve_lin(A, b):
    n = len(A[0])
    M = [[sum(A[k][i] * A[k][j] for k in range(len(A))) for j in range(n)] for i in range(n)]
    v = [sum(A[k][i] * b[k] for k in range(len(A))) for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]; v[c], v[piv] = v[piv], v[c]
        if abs(M[c][c]) < 1e-18:
            return None
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n):
                    M[r][k] -= f * M[c][k]
                v[r] -= f * v[c]
    return [v[i] / M[i][i] for i in range(n)]

def initial(P, d):
    rows, rhs = [], []
    for p, di in zip(P, d):
        rows.append([2 * p[0], 2 * p[1], -1.0])
        rhs.append(sum(c * c for c in p) - di * di)
    x = solve_lin(rows, rhs)
    if x is None:
        return None
    rest = x[2] - x[0] ** 2 - x[1] ** 2
    if rest <= 0:
        return None
    return [x[0], x[1], math.sqrt(rest)]

def gauss_newton(P, d, t, iters=6):
    for _ in range(iters):
        J, r = [], []
        for p, di in zip(P, d):
            dx, dy, dz = t[0] - p[0], t[1] - p[1], t[2] - p[2]
            r.append(dx * dx + dy * dy + dz * dz - di * di)
            J.append([2 * dx, 2 * dy, 2 * dz])
        M = [[sum(J[k][i] * J[k][j] for k in range(len(J))) for j in range(3)] for i in range(3)]
        v = [-sum(J[k][i] * r[k] for k in range(len(J))) for i in range(3)]
        det = (M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
               - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
               + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]))
        if abs(det) < 1e-30:
            break
        inv = [
            [(M[1][1]*M[2][2]-M[1][2]*M[2][1])/det, (M[0][2]*M[2][1]-M[0][1]*M[2][2])/det, (M[0][1]*M[1][2]-M[0][2]*M[1][1])/det],
            [(M[1][2]*M[2][0]-M[1][0]*M[2][2])/det, (M[0][0]*M[2][2]-M[0][2]*M[2][0])/det, (M[0][2]*M[1][0]-M[0][0]*M[1][2])/det],
            [(M[1][0]*M[2][1]-M[1][1]*M[2][0])/det, (M[0][1]*M[2][0]-M[0][0]*M[2][1])/det, (M[0][0]*M[1][1]-M[0][1]*M[1][0])/det],
        ]
        dlt = [sum(inv[i][j] * v[j] for j in range(3)) for i in range(3)]
        for i in range(3):
            t[i] += dlt[i]
        if sum(abs(x) for x in dlt) < 1e-9:
            break
    return t

def locate(P, d):
    t0 = initial(P, d)
    if t0 is None:
        return None
    return gauss_newton(P, d, t0)

def build(pitch, dome):
    P = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            z = dome * (dx * dx + dy * dy) / 2.0 / 1000.0
            P.append([dx * pitch / 1000.0, dy * pitch / 1000.0, z])
    return P

def run(pitch, dome, z_mm, noise_mm, trials=300, seed=7):
    rnd = random.Random(seed)
    P = build(pitch, dome)
    truth = (0.006, -0.004, z_mm / 1000.0)
    d0 = [math.sqrt(sum((truth[i] - p[i]) ** 2 for i in range(3))) for p in P]
    errs = []
    for _ in range(trials):
        d = [v + rnd.gauss(0, noise_mm / 1000.0) for v in d0]
        t = locate(P, d)
        if t is None:
            continue
        errs.append(math.sqrt(sum((t[i] - truth[i]) ** 2 for i in range(3))) * 1000)
    if not errs:
        return float('nan')
    errs.sort()
    return errs[len(errs) // 2]

def beam(D_mm):
    D = D_mm / 1000.0
    return math.degrees(0.51 * LAMBDA / D), math.degrees(1.22 * LAMBDA / D)

print("=" * 70)
print("声束宽度（水中 3.5MHz，lambda = %.3f mm）" % (LAMBDA * 1000))
print("%-10s %-14s %-14s %-10s" % ("探头直径", "-6dB半角", "首零点半角", "80mm处光斑半径"))
for D in (2, 4, 6, 8, 10, 12):
    a6, a0 = beam(D)
    print("%-10s %-14s %-14s %-10s" % ("%d mm" % D, "%.2f°" % a6, "%.2f°" % a0,
                                      "%.1f mm" % (80 * math.tan(math.radians(a6)))))
print()
print("=> PZT 波束很窄：8mm 片在 80mm 处只有 ±2.2mm 光斑。9 片平行朝前时，")
print("   四角探头离轴 35mm（PITCH=25mm），目标根本进不了声束 —— 必须倾斜对焦。")
print("=" * 70)

print()
print("Q1 孔径扫描（共面平行，z=80mm，测距噪声 sigma=0.15mm）")
print("%-12s %-16s %-16s" % ("PITCH", "中位误差(mm)", "相对误差(%)"))
for pitch in (5, 10, 15, 20, 25, 30, 40):
    e = run(pitch, 0, 80, 0.15)
    print("%-12s %-16.3f %-16.2f" % ("%d mm" % pitch, e, e / 80 * 100))

print()
print("Q2 拱高扫描（PITCH=25mm，z=80mm，sigma=0.15mm）")
print("球面冠：四角探头半径 r=35.36mm，冠半径 R=(r^2+h^2)/(2h)，各片法线交于 z=R")
print("%-8s %-10s %-12s %-12s %-14s %-12s" %
      ("拱高h", "冠半径R", "焦点距离", "四角法线倾角", "中位误差(mm)", "相对误差(%)"))
for h in (0, 1, 2, 4, 6, 8, 10, 12):
    r = math.sqrt(2) * 25.0
    if h == 0:
        print("%-8s %-10s %-12s %-12s %-14.3f %-12.2f" %
              ("0 mm", "inf", "inf", "0.0°", run(25, 0, 80, 0.15), run(25, 0, 80, 0.15) / 80 * 100))
        continue
    R = (r * r + h * h) / (2 * h)
    tilt = math.degrees(math.asin(r / R))
    e = run(25, h, 80, 0.15)
    print("%-8s %-10s %-12s %-12s %-14.3f %-12.2f" %
          ("%d mm" % h, "%.1f mm" % R, "%.1f mm" % R, "%.1f°" % tilt, e, e / 80 * 100))

print()
print("Q3 噪声灵敏度（PITCH=25mm，h=6mm，z=80mm）")
print("%-14s %-16s" % ("测距噪声(mm)", "中位误差(mm)"))
for nz in (0.05, 0.10, 0.15, 0.30, 0.50, 1.00):
    e = run(25, 6, 80, nz)
    print("%-14s %-16.3f" % ("%.2f" % nz, e))
