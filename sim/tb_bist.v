`timescale 1ns / 1ps

module tb_bist;
    reg         clk;
    reg         rst_n;
    wire        adc_clk, tx_pwm, uart_txd, led;
    wire [3:0]  tx_sel;
    wire [2:0]  dbg_state;
    wire [11:0] dbg_tof;
    wire [9:0]  dbg_peak;

    top_ultrasonic #(
        .TEST_MODE(1), .PRF_MS(1), .BLANK_C(1000), .THRESH(10'd20), .BAUD(5_000_000)
    ) dut (
        .clk(clk), .rst_n(rst_n), .adc_data(10'd512), .adc_ovr(1'b0),
        .adc_clk(adc_clk), .adc_oe(), .tx_pwm(tx_pwm), .tx_sel(tx_sel),
        .uart_txd(uart_txd), .led(led), .dbg_state(dbg_state),
        .dbg_tof(dbg_tof), .dbg_peak(dbg_peak)
    );

    initial clk = 1'b0;
    always #4 clk = ~clk;

    integer frame_bytes = 0;
    reg [7:0] first_byte = 0, second_byte = 0;
    always @(posedge clk) if (dut.tx_send) begin
        frame_bytes = frame_bytes + 1;
        if (frame_bytes == 1) first_byte  = dut.tx_data;
        if (frame_bytes == 2) second_byte = dut.tx_data;
    end

    integer hit_of_ch [0:15];
    integer peak_of_ch [0:15];
    integer ch_cnt [0:15];
    integer ci;
    initial begin
        for (ci = 0; ci < 16; ci = ci + 1) begin
            hit_of_ch[ci] = -1; peak_of_ch[ci] = 0; ch_cnt[ci] = 0;
        end
    end
    always @(posedge clk) if (dut.frm_go) begin
        hit_of_ch[dut.ch_idx]  = dut.hit_idx;
        peak_of_ch[dut.ch_idx] = dut.peak;
        ch_cnt[dut.ch_idx]     = ch_cnt[dut.ch_idx] + 1;
        $display("[BIST] ch=%0d  hit_idx=%0d  peak=%0d  tx_sel=%b",
                 dut.ch_idx, dut.hit_idx, dut.peak, tx_sel);
    end

    integer errors;
    initial begin
        errors = 0;
        rst_n = 1'b0;
        #200 rst_n = 1'b1;
        #12_000_000;

        $display("================================================");
        for (ci = 0; ci < 9; ci = ci + 1) begin
            $display("  ch%0d: hit=%0d peak=%0d count=%0d", ci, hit_of_ch[ci], peak_of_ch[ci], ch_cnt[ci]);
            if (ch_cnt[ci] < 1)                          errors = errors + 1;
            if (hit_of_ch[ci] < 380 || hit_of_ch[ci] > 430) errors = errors + 1;
            if (peak_of_ch[ci] < 50)                     errors = errors + 1;
        end
        if (ch_cnt[9] != 0) errors = errors + 1;
        if (!(first_byte == 8'hAA && second_byte == 8'h55 && frame_bytes >= 260)) begin
            $display("  FRAME BAD: first=%02h second=%02h bytes=%0d", first_byte, second_byte, frame_bytes);
            errors = errors + 1;
        end
        if (tx_sel !== ~dut.ch_idx) begin
            $display("  TX_SEL BAD"); errors = errors + 1;
        end
        $display("  frame_bytes=%0d first=%02h second=%02h", frame_bytes, first_byte, second_byte);
        if (errors == 0) $display("RESULT: BIST PASS (internal echo -> TOF/peak/frame/scan all OK)");
        else             $display("RESULT: BIST FAIL (%0d errors)", errors);
        $display("================================================");
        $finish;
    end
endmodule
