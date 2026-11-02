set outdir [file normalize "./synth_out"]
file mkdir $outdir

read_verilog [glob ../rtl/*.v]
read_xdc ../rtl/top_ultrasonic.xdc

synth_design -top top_ultrasonic -part xc7a35tfgg484-2 -flatten_hierarchy rebuilt

create_clock -period 10.000 -name clk [get_ports clk]

report_utilization -file $outdir/util.rpt
report_timing_summary -file $outdir/timing_synth.rpt
report_design_analysis -file $outdir/design_analysis.rpt -logic_level_distribution
write_checkpoint -force $outdir/post_synth.dcp

puts "==== SYNTH DONE ===="
