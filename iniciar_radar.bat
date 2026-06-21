@echo off
color 0A
title Lanzador AERO-LITORAL 26 (Testbench ADS-B)

:: Cambiar al directorio donde esta el .bat (soluciona el error al correr como Admin)
cd /d "%~dp0"

echo ========================================================
echo     AERO-LITORAL 26 -- Inicializando Testbench ADS-B
echo ========================================================
echo.
echo Iniciando el Receptor de Radio (GNU Radio)...
start "Receptor ADS-B (RTL-SDR)" /HIGH cmd /k "C:\ProgramData\radioconda\Scripts\activate.bat && python adsb_rx_completo.py"

echo.
echo Esperando 10 segundos a que la antena y el puerto ZMQ se abran...
timeout /t 10 /nobreak > NUL

echo.
echo Iniciando el Decodificador Profundo (Python)...
start "Decodificador ADS-B (pyModeS)" cmd /k "C:\ProgramData\radioconda\Scripts\activate.bat && python adsb_decoder.py --zmq"

echo.
echo Iniciando Servidor Web (LITORAL-RADAR-FRP)...
start "LITORAL-RADAR Web Server" /MIN cmd /c "C:\ProgramData\radioconda\Scripts\activate.bat && python -m http.server 8080 --directory web"
timeout /t 2 /nobreak > NUL
start http://localhost:8080

echo.
echo ========================================================
echo   Todo el sistema esta corriendo.
echo   Podes minimizar esta ventana.
echo ========================================================
echo.
pause
