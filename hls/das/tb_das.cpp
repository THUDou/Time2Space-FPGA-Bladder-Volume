
#include <cstdio>
#include <cmath>
#include <cstdlib>
#include <ap_int.h>

#define NCH   9
#define NSAMP 4096
#define NPIX  4096
extern void das_beamform(const ap_uint<10>* rf, const ap_uint<16>* del, ap_uint<16>* out);

static const double C_TISSUE = 1.5;
static const double R_CAP = 82.0, PITCH = 25.0;
static const double W_MM = 80.0, D_MM = 140.0;
static const int G = 64;
static const double DX = W_MM / G, DZ = D_MM / G;
static const double FS = 25.0;
static const double DT = 1.0 / FS;

static void ch_xy(int k, double &x, double &z) {
    int r = k / 3, c = k % 3;
    double y = (r - 1) * PITCH, xx = (c - 1) * PITCH;
    x = xx;
    z = R_CAP - sqrt(R_CAP * R_CAP - (xx * xx + y * y));
}

int main() {
    static ap_uint<10> rf[NCH * NSAMP];
    static ap_uint<16> del[NCH * NPIX];
    static ap_uint<16> out[NPIX];

    const int TP = 20 * G + 32;
    double tx = (32 + 0.5) * DX - W_MM / 2.0;
    double tz = (20 + 0.5) * DZ;

    for (int k = 0; k < NCH * NSAMP; k++) rf[k] = 0;

    for (int ch = 0; ch < NCH; ch++) {
        double x1, z1; ch_xy(ch, x1, z1);
        double d = sqrt((tx - x1) * (tx - x1) + (tz - z1) * (tz - z1));
        int idx = (int)(2.0 * d / C_TISSUE / DT);
        for (int n = -2; n <= 2; n++) {
            int ii = idx + n;
            if (ii >= 0 && ii < NSAMP) rf[ch * NSAMP + ii] = (n == 0) ? 900 : 300;
        }
    }

    for (int k = 0; k < NPIX; k++) {
        int pz = k / G, px = k % G;
        double X = (px + 0.5) * DX - W_MM / 2.0;
        double Z = (pz + 0.5) * DZ;
        for (int ch = 0; ch < NCH; ch++) {
            double x1, z1; ch_xy(ch, x1, z1);
            double d = sqrt((X - x1) * (X - x1) + (Z - z1) * (Z - z1));
            int idx = (int)(2.0 * d / C_TISSUE / DT);
            if (idx < 0) idx = 0;
            if (idx > NSAMP - 1) idx = NSAMP - 1;
            del[ch * NPIX + k] = (ap_uint<16>)idx;
        }
    }

    das_beamform(rf, del, out);

    int best = 0;
    for (int i = 1; i < NPIX; i++) if (out[i] > out[best]) best = i;
    int bz = best / G, bx = best % G;
    printf("peak pixel = (%d,%d)  expect (32,20)  value=%d\n", bx, bz, (int)out[best]);

    int tz2 = TP / G, tx2 = TP % G;
    bool ok = (abs(bx - tx2) <= 1) && (abs(bz - tz2) <= 1);
    printf("%s\n", ok ? "RESULT: PASS" : "RESULT: FAIL");
    return ok ? 0 : 1;
}
