open_project -reset das_prj
set_top das_beamform
add_files das_beamform.cpp
add_files -tb tb_das.cpp
open_solution -reset "sol1" -flow_target vivado
set_part {xc7z020clg400-1}
create_clock -period 10 -name default
csim_design -clean
csynth_design
exit
