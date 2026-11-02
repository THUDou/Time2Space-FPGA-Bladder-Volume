
set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33} [get_ports clk]
create_clock -period 8.000 -name pl_clk125 [get_ports clk]

set_property -dict {PACKAGE_PIN Y18 IOSTANDARD LVCMOS33} [get_ports {adc_data[0]}]
set_property -dict {PACKAGE_PIN Y19 IOSTANDARD LVCMOS33} [get_ports {adc_data[1]}]
set_property -dict {PACKAGE_PIN Y16 IOSTANDARD LVCMOS33} [get_ports {adc_data[2]}]
set_property -dict {PACKAGE_PIN Y17 IOSTANDARD LVCMOS33} [get_ports {adc_data[3]}]
set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVCMOS33} [get_ports {adc_data[4]}]
set_property -dict {PACKAGE_PIN U19 IOSTANDARD LVCMOS33} [get_ports {adc_data[5]}]
set_property -dict {PACKAGE_PIN W18 IOSTANDARD LVCMOS33} [get_ports {adc_data[6]}]
set_property -dict {PACKAGE_PIN W19 IOSTANDARD LVCMOS33} [get_ports {adc_data[7]}]

set_property -dict {PACKAGE_PIN W14 IOSTANDARD LVCMOS33} [get_ports {adc_data[8]}]
set_property -dict {PACKAGE_PIN Y14 IOSTANDARD LVCMOS33} [get_ports {adc_data[9]}]
set_property -dict {PACKAGE_PIN T11 IOSTANDARD LVCMOS33} [get_ports adc_ovr]
set_property -dict {PACKAGE_PIN T10 IOSTANDARD LVCMOS33} [get_ports tx_pwm]
set_property -dict {PACKAGE_PIN V16 IOSTANDARD LVCMOS33} [get_ports adc_clk]
set_property -dict {PACKAGE_PIN W15 IOSTANDARD LVCMOS33} [get_ports uart_txd]
set_property -dict {PACKAGE_PIN V12 IOSTANDARD LVCMOS33} [get_ports adc_oe]

set_property -dict {PACKAGE_PIN T14 IOSTANDARD LVCMOS33} [get_ports {tx_sel[0]}]
set_property -dict {PACKAGE_PIN U12 IOSTANDARD LVCMOS33} [get_ports {tx_sel[1]}]
set_property -dict {PACKAGE_PIN U13 IOSTANDARD LVCMOS33} [get_ports {tx_sel[2]}]
set_property -dict {PACKAGE_PIN V13 IOSTANDARD LVCMOS33} [get_ports {tx_sel[3]}]

set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports led]
set_property -dict {PACKAGE_PIN M20 IOSTANDARD LVCMOS33} [get_ports rst_n]

set_false_path -from [get_ports {adc_data[*] adc_ovr}]
