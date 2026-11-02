
#include <ap_int.h>

#define NCH   9
#define NSAMP 4096
#define NPIX  4096

void das_beamform(const ap_uint<10>* rf,
                  const ap_uint<16>* del,
                  ap_uint<16>* out)
{
#pragma HLS INTERFACE m_axi     port=rf  offset=slave bundle=gmem0 depth=NCH*NSAMP
#pragma HLS INTERFACE m_axi     port=del offset=slave bundle=gmem1 depth=NCH*NPIX
#pragma HLS INTERFACE m_axi     port=out offset=slave bundle=gmem2 depth=NPIX
#pragma HLS INTERFACE s_axilite port=return

    ap_uint<10> buf[NCH][NSAMP];
#pragma HLS ARRAY_PARTITION variable=buf complete dim=1

    ap_uint<16> dly[NCH];

LOAD_RF:
    for (int ch = 0; ch < NCH; ch++) {
#pragma HLS LOOP_TRIPCOUNT min=9 max=9
        for (int n = 0; n < NSAMP; n++) {
#pragma HLS PIPELINE II=1
            buf[ch][n] = rf[ch * NSAMP + n];
        }
    }

PIX:
    for (int p = 0; p < NPIX; p++) {
#pragma HLS LOOP_TRIPCOUNT min=4096 max=4096

    LOAD_DLY:
        for (int ch = 0; ch < NCH; ch++) {
#pragma HLS UNROLL
            dly[ch] = del[ch * NPIX + p];
        }

        ap_uint<14> acc = 0;
    ACC:
        for (int ch = 0; ch < NCH; ch++) {
#pragma HLS UNROLL
            ap_uint<16> idx = dly[ch];
            ap_uint<10> v = buf[ch][idx];
            acc += v;
        }
        out[p] = (ap_uint<16>)acc;
    }
}
