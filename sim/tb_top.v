`timescale 1ns / 1ps

module tb_top;

    reg         clk;
    reg         rst_n;
    reg  [9:0]  adc_data;
    wire        adc_clk;
    wire        tx_pwm;
    wire [3:0]  tx_sel;
    wire        uart_txd;
    wire        led;
    wire [2:0]  dbg_state;
    wire [11:0] dbg_tof;
    wire [9:0]  dbg_peak;

    top_ultrasonic #(
        .PRF_MS(1), .BLANK_C(1000), .THRESH(10'd20), .BAUD(5_000_000)
    )     dut (
        .clk(clk), .rst_n(rst_n), .adc_data(adc_data),
        .adc_ovr(1'b0), .adc_clk(adc_clk), .adc_oe(),
        .tx_pwm(tx_pwm), .tx_sel(tx_sel), .uart_txd(uart_txd),
        .led(led), .dbg_state(dbg_state), .dbg_tof(dbg_tof), .dbg_peak(dbg_peak)
    );

    initial clk = 1'b0;
    always #4 clk = ~clk;

    integer sin_tab [0:63];
    initial begin
        sin_tab[0]=0;   sin_tab[1]=12;  sin_tab[2]=25;  sin_tab[3]=37;
        sin_tab[4]=49;  sin_tab[5]=60;  sin_tab[6]=71;  sin_tab[7]=81;
        sin_tab[8]=90;  sin_tab[9]=98;  sin_tab[10]=106;sin_tab[11]=112;
        sin_tab[12]=117;sin_tab[13]=122;sin_tab[14]=125;sin_tab[15]=126;
        sin_tab[16]=127;sin_tab[17]=126;sin_tab[18]=125;sin_tab[19]=122;
        sin_tab[20]=117;sin_tab[21]=112;sin_tab[22]=106;sin_tab[23]=98;
        sin_tab[24]=90; sin_tab[25]=81; sin_tab[26]=71; sin_tab[27]=60;
        sin_tab[28]=49; sin_tab[29]=37; sin_tab[30]=25; sin_tab[31]=12;
        sin_tab[32]=0;  sin_tab[33]=-12;sin_tab[34]=-25;sin_tab[35]=-37;
        sin_tab[36]=-49;sin_tab[37]=-60;sin_tab[38]=-71;sin_tab[39]=-81;
        sin_tab[40]=-90;sin_tab[41]=-98;sin_tab[42]=-106;sin_tab[43]=-112;
        sin_tab[44]=-117;sin_tab[45]=-122;sin_tab[46]=-125;sin_tab[47]=-126;
        sin_tab[48]=-127;sin_tab[49]=-126;sin_tab[50]=-125;sin_tab[51]=-122;
        sin_tab[52]=-117;sin_tab[53]=-112;sin_tab[54]=-106;sin_tab[55]=-98;
        sin_tab[56]=-90;sin_tab[57]=-81;sin_tab[58]=-71;sin_tab[59]=-60;
        sin_tab[60]=-49;sin_tab[61]=-37;sin_tab[62]=-25;sin_tab[63]=-12;
    end

    real    t_tx_start;
    real    t_cap_start;
    real    t_echo;
    integer phase;
    integer echo_n;
    integer amp;
    reg     echo_on;
    reg     echo_armed;

    always @(posedge dut.tx_start) begin
        t_tx_start = $realtime;
        t_echo     = t_tx_start + 30000.0;
        echo_armed = 1'b1;
    end

    always @(posedge dut.cap_start) begin
        t_cap_start = $realtime;
    end

    always @(negedge clk) begin
        if (echo_armed && ($realtime >= t_echo)) begin
            echo_on    <= 1'b1;
            echo_armed <= 1'b0;
            echo_n     <= 0;
            phase      <= 0;
            amp        <= 120;
        end else if (echo_on) begin
            adc_data <= 512 + ((sin_tab[phase] * amp) >>> 7);
            phase    <= (phase + 9) & 63;
            echo_n   <= echo_n + 1;
            amp      <= (amp > 12) ? amp - 1 : 0;
            if (echo_n > 250) echo_on <= 1'b0;
        end else begin
            adc_data <= 10'd512;
        end
    end

    always @(posedge dut.hit) begin
        $display("[DBG] HIT at %0t ns, sample_idx=%0d, env=%0d, adc=%0d",
                 $realtime, dut.smp_idx, dut.env_out, adc_data);
    end
    always @(posedge clk) begin
        if (dut.smp_valid && dut.smp_idx < 6)
            $display("[DBG] smp idx=%0d data=%0d env=%0d", dut.smp_idx, dut.smp_data, dut.env_out);
    end

    integer   frame_bytes;
    reg [7:0] first_byte, second_byte;

    initial begin
        frame_bytes = 0; first_byte = 8'h00; second_byte = 8'h00;
    end

    always @(posedge clk) begin
        if (dut.tx_send) begin
            frame_bytes = frame_bytes + 1;
            if (frame_bytes == 1) first_byte  = dut.tx_data;
            if (frame_bytes == 2) second_byte = dut.tx_data;
        end
    end

    integer ch_seen [0:15];
    integer ci;
    reg [3:0] ch_prev;
    initial begin
        for (ci = 0; ci < 16; ci = ci + 1) ch_seen[ci] = 0;
        ch_prev = 4'd15;
    end
    always @(posedge clk) begin
        if (dut.frm_go) begin
            ch_seen[dut.ch_idx] = ch_seen[dut.ch_idx] + 1;
            if (dut.ch_idx != ch_prev) begin
                $display("[CH ] t=%0t ns  ch=%0d  tx_sel=%b (应为 ~ch)", $realtime, dut.ch_idx, tx_sel);
                ch_prev = dut.ch_idx;
            end
        end
    end

    real expected_tof;
    initial begin
        rst_n    = 1'b0;
        adc_data = 10'd512;
        echo_on  = 1'b0;
        echo_armed = 1'b0;
        #200;
        rst_n = 1'b1;

        #30_000_000;

        expected_tof = (t_echo - t_cap_start) / 40.0;
        $display("================================================");
        $display("t_tx_start   = %0.1f ns", t_tx_start);
        $display("t_cap_start  = %0.1f ns", t_cap_start);
        $display("t_echo       = %0.1f ns", t_echo);
        $display("expected TOF = %0.1f samples", expected_tof);
        $display("measured TOF = %0d samples  (peak=%0d)", dbg_tof, dbg_peak);
        $display("TX bytes     = %0d  (first=%02h second=%02h)", frame_bytes, first_byte, second_byte);

        if (dbg_tof > expected_tof - 12 && dbg_tof < expected_tof + 12)
            $display("RESULT: PASS  (TOF within +-12 samples)");
        else
            $display("RESULT: FAIL  (TOF deviation too large)");

        if (first_byte == 8'hAA && second_byte == 8'h55 && frame_bytes >= 260)
            $display("RESULT: FRAME OK (%0d bytes)", frame_bytes);
        else
            $display("RESULT: FRAME INCOMPLETE");

        for (ci = 0; ci < 9; ci = ci + 1)
            $display("        ch%0d 发送次数 = %0d", ci, ch_seen[ci]);
        if (ch_seen[0] >= 1 && ch_seen[1] >= 1 && ch_seen[2] >= 1 && ch_seen[3] >= 1 &&
            ch_seen[4] >= 1 && ch_seen[5] >= 1 && ch_seen[6] >= 1 && ch_seen[7] >= 1 &&
            ch_seen[8] >= 1 && ch_seen[9] == 0)
            $display("RESULT: CHANNEL SCAN OK (0..8 全部命中，且未越界到 9)");
        else
            $display("RESULT: CHANNEL SCAN FAIL");

        if (tx_sel == ~dut.ch_idx)
            $display("RESULT: TX_SEL OK (tx_sel = ~ch)");
        else
            $display("RESULT: TX_SEL FAIL");

        $display("================================================");
        $finish;
    end

endmodule
