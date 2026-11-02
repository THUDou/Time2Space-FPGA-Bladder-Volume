`timescale 1ns / 1ps

module bist_echo #(
    parameter integer DIV_N     = 5,
    parameter integer DELAY_SMP = 400,
    parameter integer AMP       = 120,
    parameter integer ECHO_LEN  = 250,
    parameter integer PHASE_STEP= 9
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cap_start,
    output reg  [9:0]  adc_data
);

    integer sin_tab [0:63];
    initial begin
        sin_tab[0]=0;    sin_tab[1]=12;   sin_tab[2]=25;   sin_tab[3]=37;
        sin_tab[4]=49;   sin_tab[5]=60;   sin_tab[6]=71;   sin_tab[7]=81;
        sin_tab[8]=90;   sin_tab[9]=98;   sin_tab[10]=106; sin_tab[11]=112;
        sin_tab[12]=117; sin_tab[13]=122; sin_tab[14]=125; sin_tab[15]=126;
        sin_tab[16]=127; sin_tab[17]=126; sin_tab[18]=125; sin_tab[19]=122;
        sin_tab[20]=117; sin_tab[21]=112; sin_tab[22]=106; sin_tab[23]=98;
        sin_tab[24]=90;  sin_tab[25]=81;  sin_tab[26]=71;  sin_tab[27]=60;
        sin_tab[28]=49;  sin_tab[29]=37;  sin_tab[30]=25;  sin_tab[31]=12;
        sin_tab[32]=0;   sin_tab[33]=-12; sin_tab[34]=-25; sin_tab[35]=-37;
        sin_tab[36]=-49; sin_tab[37]=-60; sin_tab[38]=-71; sin_tab[39]=-81;
        sin_tab[40]=-90; sin_tab[41]=-98; sin_tab[42]=-106;sin_tab[43]=-112;
        sin_tab[44]=-117;sin_tab[45]=-122;sin_tab[46]=-125;sin_tab[47]=-126;
        sin_tab[48]=-127;sin_tab[49]=-126;sin_tab[50]=-125;sin_tab[51]=-122;
        sin_tab[52]=-117;sin_tab[53]=-112;sin_tab[54]=-106;sin_tab[55]=-98;
        sin_tab[56]=-90; sin_tab[57]=-81; sin_tab[58]=-71; sin_tab[59]=-60;
        sin_tab[60]=-49; sin_tab[61]=-37; sin_tab[62]=-25; sin_tab[63]=-12;
    end

    reg [7:0]  div;
    reg        pending;
    reg        echo_on;
    integer    delay_cnt;
    integer    echo_n;
    integer    phase;
    integer    amp;

    wire samp_en = (div == 8'd0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            div       <= 8'd0;
            pending   <= 1'b0;
            echo_on   <= 1'b0;
            delay_cnt <= 0;
            echo_n    <= 0;
            phase     <= 0;
            amp       <= 0;
            adc_data  <= 10'd512;
        end else begin
            div <= (div == DIV_N-1) ? 8'd0 : div + 8'd1;

            if (cap_start) begin
                pending   <= 1'b1;
                echo_on   <= 1'b0;
                delay_cnt <= 0;
                adc_data  <= 10'd512;
            end else if (samp_en) begin
                if (pending) begin
                    adc_data <= 10'd512;
                    if (delay_cnt >= DELAY_SMP-1) begin
                        pending <= 1'b0;
                        echo_on <= 1'b1;
                        echo_n  <= 0;
                        phase   <= 0;
                        amp     <= AMP;
                    end else begin
                        delay_cnt <= delay_cnt + 1;
                    end
                end else if (echo_on) begin

                    adc_data <= 10'd512 + ((sin_tab[phase] * amp) >>> 7);
                    phase    <= (phase + PHASE_STEP) & 63;
                    echo_n   <= echo_n + 1;
                    amp      <= (amp > 12) ? amp - 1 : 0;
                    if (echo_n >= ECHO_LEN-1) begin
                        echo_on  <= 1'b0;
                        adc_data <= 10'd512;
                    end
                end else begin
                    adc_data <= 10'd512;
                end
            end
        end
    end
endmodule
