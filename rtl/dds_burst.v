`timescale 1ns / 1ps

module dds_burst #(
    parameter integer CLK_HZ  = 50_000_000,
    parameter integer TONE_HZ = 3_500_000,
    parameter integer CYCLES  = 12
)(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    output reg  pwm,
    output reg  busy,
    output reg  done
);

    localparam [63:0] INC = (TONE_HZ * 64'd4294967296) / CLK_HZ;

    reg [31:0] phase;
    reg        msb_d;
    reg [15:0] half_cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase    <= 32'd0;
            msb_d    <= 1'b0;
            half_cnt <= 16'd0;
            pwm      <= 1'b0;
            busy     <= 1'b0;
            done     <= 1'b0;
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                busy     <= 1'b1;
                half_cnt <= 16'd0;
                phase    <= 32'd0;
                msb_d    <= 1'b0;
                pwm      <= 1'b0;
            end else if (busy) begin
                phase <= phase + INC[31:0];
                pwm   <= phase[31];
                if (phase[31] != msb_d) begin
                    msb_d <= phase[31];
                    if (half_cnt == (2*CYCLES - 1)) begin
                        busy <= 1'b0;
                        pwm  <= 1'b0;
                        done <= 1'b1;
                    end else begin
                        half_cnt <= half_cnt + 16'd1;
                    end
                end
            end
        end
    end
endmodule
