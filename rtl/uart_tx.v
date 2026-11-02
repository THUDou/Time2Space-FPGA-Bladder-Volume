`timescale 1ns / 1ps

module uart_tx #(
    parameter integer CLK_HZ = 50_000_000,
    parameter integer BAUD   = 460800
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] data,
    input  wire       send,
    output reg        tx,
    output reg        busy
);
    localparam integer DIV = (CLK_HZ + BAUD/2) / BAUD;

    reg [15:0] cnt;
    reg [3:0]  bit_cnt;
    reg [9:0]  shifter;
    reg        sending;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx      <= 1'b1;
            busy    <= 1'b0;
            cnt     <= 16'd0;
            bit_cnt <= 4'd0;
            shifter <= 10'h3FF;
            sending <= 1'b0;
        end else begin
            if (!sending) begin
                tx   <= 1'b1;
                busy <= 1'b0;
                if (send) begin
                    shifter <= {1'b1, data, 1'b0};
                    sending <= 1'b1;
                    busy    <= 1'b1;
                    cnt     <= 16'd0;
                    bit_cnt <= 4'd0;
                    tx      <= 1'b0;
                end
            end else begin
                if (cnt == DIV-1) begin
                    cnt <= 16'd0;
                    if (bit_cnt == 4'd9) begin
                        sending <= 1'b0;
                        busy    <= 1'b0;
                        tx      <= 1'b1;
                    end else begin
                        bit_cnt <= bit_cnt + 4'd1;
                        tx      <= shifter[bit_cnt + 4'd1];
                    end
                end else begin
                    cnt <= cnt + 16'd1;
                end
            end
        end
    end
endmodule
