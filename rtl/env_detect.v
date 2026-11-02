`timescale 1ns / 1ps

module env_detect #(
    parameter integer W  = 10,
    parameter integer AW = 12,
    parameter integer MA = 8,
    parameter integer COMP = 4
)(
    input  wire          clk,
    input  wire          rst_n,
    input  wire          clear,
    input  wire [W-1:0]  sample,
    input  wire          sample_valid,
    input  wire [AW-1:0] sample_idx,
    input  wire [W-1:0]  offset,
    input  wire [W-1:0]  thresh,
    output reg           hit,
    output reg  [AW-1:0] hit_idx,
    output reg  [W-1:0]  peak,
    output reg  [AW-1:0] peak_idx,
    output reg  [W-1:0]  env_out
);
    reg [W-1:0]  mag_hist [0:MA-1];
    reg [W+3:0]  sum;
    reg [W+3:0]  new_sum;
    reg [W-1:0]  mag;
    reg [W-1:0]  env;
    integer      i;

    always @(*) begin
        if (sample >= offset) mag = sample - offset;
        else                  mag = offset - sample;
    end

    always @(*) begin
        new_sum = sum + mag - mag_hist[MA-1];
        env     = new_sum[W+2:3];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum       <= {(W+4){1'b0}};
            hit       <= 1'b0;
            hit_idx   <= {AW{1'b0}};
            peak      <= {W{1'b0}};
            peak_idx  <= {AW{1'b0}};
            env_out   <= {W{1'b0}};
            for (i = 0; i < MA; i = i + 1) mag_hist[i] <= {W{1'b0}};
        end else if (clear) begin
            sum       <= {(W+4){1'b0}};
            hit       <= 1'b0;
            hit_idx   <= {AW{1'b0}};
            peak      <= {W{1'b0}};
            peak_idx  <= {AW{1'b0}};
            env_out   <= {W{1'b0}};
            for (i = 0; i < MA; i = i + 1) mag_hist[i] <= {W{1'b0}};
        end else if (sample_valid) begin
            for (i = MA-1; i > 0; i = i - 1) mag_hist[i] <= mag_hist[i-1];
            mag_hist[0] <= mag;
            sum     <= new_sum;
            env_out <= env;

            if (env > peak) begin
                peak     <= env;
                peak_idx <= sample_idx;
            end

            if (!hit && env > thresh) begin
                hit     <= 1'b1;
                hit_idx <= (sample_idx > COMP) ? (sample_idx - COMP) : {AW{1'b0}};
            end
        end
    end
endmodule
