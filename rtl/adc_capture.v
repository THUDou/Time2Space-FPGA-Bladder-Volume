`timescale 1ns / 1ps

module adc_capture #(
    parameter integer W     = 10,
    parameter integer DEPTH = 4096,
    parameter integer AW    = 12,
    parameter integer DIV_N = 4,
    parameter integer SAMPLE_PHASE = 2
)(
    input  wire          clk,
    input  wire          rst_n,
    input  wire          start,
    input  wire [W-1:0]  adc_data,
    output reg  [W-1:0]  sample,
    output reg           sample_valid,
    output reg  [AW-1:0] sample_idx,
    output reg           done,
    input  wire [AW-1:0] rd_addr,
    output reg  [W-1:0]  rd_data
);
    (* ram_style = "block" *) reg [W-1:0]  ram [0:DEPTH-1];
    reg [AW-1:0] widx;
    reg [7:0]    div;
    reg          capturing;

    always @(posedge clk) begin
        rd_data <= ram[rd_addr];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            widx         <= {AW{1'b0}};
            div          <= 8'd0;
            capturing    <= 1'b0;
            sample       <= {W{1'b0}};
            sample_valid <= 1'b0;
            sample_idx   <= {AW{1'b0}};
            done         <= 1'b0;
        end else begin
            sample_valid <= 1'b0;
            done         <= 1'b0;

            if (start && !capturing) begin
                capturing <= 1'b1;
                widx      <= {AW{1'b0}};
                div       <= 8'd0;
            end else if (capturing) begin
                div <= (div == DIV_N-1) ? 8'd0 : div + 8'd1;
                if (div == SAMPLE_PHASE) begin
                    ram[widx]    <= adc_data;
                    sample       <= adc_data;
                    sample_idx   <= widx;
                    sample_valid <= 1'b1;
                    if (widx == DEPTH-1) begin
                        capturing <= 1'b0;
                        done      <= 1'b1;
                    end else begin
                        widx <= widx + 1'b1;
                    end
                end
            end
        end
    end
endmodule
