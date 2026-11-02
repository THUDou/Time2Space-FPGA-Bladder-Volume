@echo off
set VIVADO_BIN=E:\Xilinx\Vivado\2022.2\bin
cd /d %~dp0
if exist xsim.dir rmdir /s /q xsim.dir
if exist xvlog.log del xvlog.log
if exist xelab.log del xelab.log

call "%VIVADO_BIN%\xvlog.bat" -sv ..\rtl\dds_burst.v ..\rtl\adc_capture.v ..\rtl\env_detect.v ..\rtl\uart_tx.v ..\rtl\frame_sender.v ..\rtl\top_ultrasonic.v tb_top.v
if errorlevel 1 goto :err

call "%VIVADO_BIN%\xelab.bat" tb_top -debug typical -s tb_sim
if errorlevel 1 goto :err

call "%VIVADO_BIN%\xsim.bat" tb_sim -runall
goto :eof

:err
echo.
echo ***** BUILD FAILED *****
exit /b 1
