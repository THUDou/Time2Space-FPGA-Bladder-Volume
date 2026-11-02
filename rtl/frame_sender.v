`timescale 1ns / 1ps

module frame_sender #(
    parameter integer AW   = 12,
    parameter integer W    = 10,
    parameter integer N    = 256,
    parameter integer STEP = 16
)(
    input  wire          clk,
    input  wire          rst_n,
    input  wire          go,
    input  wire [3:0]    ch,
    input  wire [AW-1:0] hit_idx,
    input  wire [W-1:0]  peak,
    output reg  [AW-1:0] rd_addr,
    input  wire [W-1:0]  rd_data,
    output reg  [7:0]    tx_data,
    output reg           tx_send,
    input  wire          tx_busy,
    output reg           busy
);

    localparam S_IDLE = 3'd0,
               S_PREP = 3'd1,
               S_RD   = 3'd2,
               S_SEND = 3'd3,
               S_WHI  = 3'd4,
               S_WLO  = 3'd5,
               S_ADV  = 3'd6;

    localparam P_HDR  = 2'd0,
               P_SAMP = 2'd1,
               P_TAIL = 2'd2;

    reg [2:0]  state;
    reg [1:0]  phase;
    reg [3:0]  hdr_cnt;
    reg [8:0]  samp_cnt;

    reg [7:0] hdr_byte;
    always @(*) begin
        case (hdr_cnt)
            4'd0: hdr_byte = 8'hAA;
            4'd1: hdr_byte = 8'h55;
            4'd2: hdr_byte = {4'h0, ch};
            4'd3: hdr_byte = hit_idx[7:0];
            4'd4: hdr_byte = {4'h0, hit_idx[11:8]};
            4'd5: hdr_byte = peak[7:0];
            4'd6: hdr_byte = {6'h0, peak[9:8]};
            default: hdr_byte = 8'h00;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_IDLE;
            phase    <= P_HDR;
            hdr_cnt  <= 4'd0;
            samp_cnt <= 9'd0;
            rd_addr  <= {AW{1'b0}};
            tx_data  <= 8'h00;
            tx_send  <= 1'b0;
            busy     <= 1'b0;
        end else begin
            tx_send <= 1'b0;

            case (state)
                S_IDLE: begin
                    busy <= 1'b0;
                    if (go) begin
                        busy     <= 1'b1;
                        phase    <= P_HDR;
                        hdr_cnt  <= 4'd0;
                        samp_cnt <= 9'd0;
                        state    <= S_PREP;
                    end
                end

                S_PREP: begin
                    case (phase)
                        P_HDR: begin
                            tx_data <= hdr_byte;
                            state   <= S_SEND;
                        end
                        P_SAMP: begin
                            rd_addr <= samp_cnt * STEP;
                            state   <= S_RD;
                        end
                        default: begin
                            tx_data <= 8'h0D;
                            state   <= S_SEND;
                        end
                    endcase
                end

                S_RD: begin
                    tx_data <= {2'b00, rd_data[W-1:W-8]};
                    state   <= S_SEND;
                end

                S_SEND: begin
                    tx_send <= 1'b1;
                    state   <= S_WHI;
                end

                S_WHI: begin
                    if (tx_busy) state <= S_WLO;
                end

                S_WLO: begin
                    if (!tx_busy) state <= S_ADV;
                end

                S_ADV: begin
                    case (phase)
                        P_HDR: begin
                            if (hdr_cnt == 4'd6) begin
                                phase <= P_SAMP;
                            end else begin
                                hdr_cnt <= hdr_cnt + 4'd1;
                            end
                            state <= S_PREP;
                        end
                        P_SAMP: begin
                            if (samp_cnt == N-1) begin
                                phase <= P_TAIL;
                            end else begin
                                samp_cnt <= samp_cnt + 9'd1;
                            end
                            state <= S_PREP;
                        end
                        default: begin
                            busy  <= 1'b0;
                            state <= S_IDLE;
                        end
                    endcase
                end

                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
