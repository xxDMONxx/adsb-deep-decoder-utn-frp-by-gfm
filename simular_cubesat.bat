@echo off
title LITORAL-RADAR-FRP - Simulador CubeSat
color 0a

echo +====================================================================+
echo ^|                                                                    ^|
echo ^|         AERO-LITORAL 26 -- ADS-B / Mode-S ATC Dashboard            ^|
echo ^|                     SIMULADOR CUBESAT                              ^|
echo ^|                                                                    ^|
echo +====================================================================+
echo.
echo Iniciando envio de telemetria simulada (UDP 5556)...
echo Presione CTRL+C para detener.
echo.

python simulador_cubesat.py

pause
