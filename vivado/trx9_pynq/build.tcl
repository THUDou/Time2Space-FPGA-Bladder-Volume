set part xc7z020clg400-1
set top  top_ultrasonic

read_verilog [glob ../../rtl/*.v]
read_xdc     ../../rtl/top_ultrasonic.xdc

set_property SEVERITY {Warning} [get_drc_checks {UCIO-1}]
set_property SEVERITY {Warning} [get_drc_checks {NSTD-1}]

synth_design -top $top -part $part -flatten_hierarchy rebuilt
opt_design
place_design
route_design

report_drc             -file drc_impl.rpt
report_timing_summary  -file timing_impl.rpt
report_utilization     -file util_impl.rpt
write_bitstream -force trx9_pynq.bit

puts "BITSTREAM_DONE"
exit
