`timescale 1ns / 1ps

module top_ultrasonic #(
    parameter integer CLK_HZ  = 125_000_000,
    parameter integer BAUD    = 460800,
    parameter integer ADC_DIV = 5,
    parameter integer DEPTH   = 4096,
    parameter integer AW      = 12,
    parameter integer PRF_MS  = 10,
    parameter integer BLANK_C = 1250,
    parameter integer THRESH  = 10'd24,
    parameter integer NCH     = 9,
    parameter integer TEST_MODE = 0
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [9:0]  adc_data,
    input  wire        adc_ovr,
    output wire        adc_clk,
    output wire        adc_oe,
    output wire        tx_pwm,
    output wire [3:0]  tx_sel,
    output wire        uart_txd,
    output wire        led,
    output reg  [2:0]  dbg_state,
    output wire [11:0] dbg_tof,
    output wire [9:0]  dbg_peak
);
    assign adc_oe = 1'b0;

    reg [3:0] ch_idx;
    assign tx_sel = ~ch_idx;

    reg [2:0] adc_div;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) adc_div <= 3'd0;
        else        adc_div <= (adc_div == ADC_DIV-1) ? 3'd0 : adc_div + 3'd1;
    end
    assign adc_clk = (adc_div < ADC_DIV/2);

    reg  tx_start;
    wire tx_dds_busy, tx_dds_done;

    dds_burst #(
        .CLK_HZ(CLK_HZ), .TONE_HZ(3_500_000), .CYCLES(12)
    ) u_burst (
        .clk(clk), .rst_n(rst_n), .start(tx_start),
        .pwm(tx_pwm), .busy(tx_dds_busy), .done(tx_dds_done)
    );

    reg          cap_start;
    wire         cap_done;
    wire [9:0]   smp_data;
    wire         smp_valid;
    wire [AW-1:0] smp_idx;
    wire [AW-1:0] rd_addr;
    wire [9:0]   rd_data;

    wire [9:0] adc_data_eff;
    generate
        if (TEST_MODE) begin : g_bist
            bist_echo #(.DIV_N(ADC_DIV), .DELAY_SMP(400), .AMP(120)) u_bist (
                .clk(clk), .rst_n(rst_n), .cap_start(cap_start), .adc_data(adc_data_eff)
            );
        end else begin : g_passthru
            assign adc_data_eff = adc_data;
        end
    endgenerate

    adc_capture #(.W(10), .DEPTH(DEPTH), .AW(AW), .DIV_N(ADC_DIV)) u_cap (
        .clk(clk), .rst_n(rst_n), .start(cap_start), .adc_data(adc_data_eff),
        .sample(smp_data), .sample_valid(smp_valid), .sample_idx(smp_idx),
        .done(cap_done), .rd_addr(rd_addr), .rd_data(rd_data)
    );

    reg          env_clear;
    wire         hit;
    wire [AW-1:0] hit_idx;
    wire [9:0]   peak;
    wire [AW-1:0] peak_idx;
    wire [9:0]   env_out;

    env_detect #(.W(10), .AW(AW), .MA(8), .COMP(4)) u_env (
        .clk(clk), .rst_n(rst_n), .clear(env_clear),
        .sample(smp_data), .sample_valid(smp_valid), .sample_idx(smp_idx),
        .offset(10'd512), .thresh(THRESH),
        .hit(hit), .hit_idx(hit_idx),
        .peak(peak), .peak_idx(peak_idx), .env_out(env_out)
    );

    wire [7:0] tx_data;
    wire       tx_send;
    wire       tx_busy;
    reg        frm_go;

    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_uart (
        .clk(clk), .rst_n(rst_n), .data(tx_data), .send(tx_send),
        .tx(uart_txd), .busy(tx_busy)
    );

    wire frm_busy;
    frame_sender #(.AW(AW), .W(10), .N(256), .STEP(16)) u_frame (
        .clk(clk), .rst_n(rst_n), .go(frm_go), .ch(ch_idx),
        .hit_idx(hit_idx), .peak(peak),
        .rd_addr(rd_addr), .rd_data(rd_data),
        .tx_data(tx_data), .tx_send(tx_send), .tx_busy(tx_busy),
        .busy(frm_busy)
    );

    localparam S_IDLE  = 3'd0,
               S_BURST = 3'd1,
               S_BLANK = 3'd2,
               S_CAP   = 3'd3,
               S_SEND  = 3'd4,
               S_SENDW = 3'd5;

    reg [2:0]  state;
    reg [31:0] prf_cnt;
    reg [15:0] blank_cnt;
    reg        prf_tick;

    localparam integer PRF_MAX = CLK_HZ/1000*PRF_MS;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_IDLE;
            prf_cnt  <= 32'd0;
            blank_cnt<= 16'd0;
            prf_tick <= 1'b0;
            tx_start <= 1'b0;
            cap_start<= 1'b0;
            env_clear<= 1'b0;
            frm_go   <= 1'b0;
            dbg_state<= 3'd0;
            ch_idx   <= 4'd0;
        end else begin
            tx_start  <= 1'b0;
            cap_start <= 1'b0;
            env_clear <= 1'b0;
            frm_go    <= 1'b0;
            dbg_state <= state;

            if (prf_cnt >= PRF_MAX-1) begin
                prf_cnt  <= 32'd0;
                prf_tick <= 1'b1;
            end else begin
                prf_cnt  <= prf_cnt + 32'd1;
                prf_tick <= 1'b0;
            end

            case (state)
                S_IDLE: begin
                    if (prf_tick) begin
                        env_clear <= 1'b1;
                        tx_start  <= 1'b1;
                        state     <= S_BURST;
                    end
                end

                S_BURST: begin
                    if (tx_dds_done) begin
                        blank_cnt <= 16'd0;
                        state     <= S_BLANK;
                    end
                end

                S_BLANK: begin
                    if (blank_cnt >= BLANK_C) begin
                        cap_start <= 1'b1;
                        state     <= S_CAP;
                    end else begin
                        blank_cnt <= blank_cnt + 16'd1;
                    end
                end

                S_CAP: begin
                    if (cap_done) begin
                        frm_go <= 1'b1;
                        state  <= S_SEND;
                    end
                end

                S_SEND: begin
                    if (frm_busy) state <= S_SENDW;
                end

                S_SENDW: begin
                    if (!frm_busy) begin

                        if (ch_idx >= NCH - 1) ch_idx <= 4'd0;
                        else                           ch_idx <= ch_idx + 4'd1;
                        state <= S_IDLE;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    assign dbg_tof  = hit_idx;
    assign dbg_peak = peak;

    reg [25:0] led_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) led_cnt <= 26'd0;
        else        led_cnt <= led_cnt + 26'd1;
    end
    assign led = led_cnt[25];
endmodule
