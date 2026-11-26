@echo off
rem Start beide loggers (MIV en Verkeerscentrum) tot de opgegeven tijd, bv.  opname.bat 10:15
rem Met een begintijd en tag start ook een live-run met viewer:  opname.bat 10:15 6:15 live_2026-11-27
rem   -> uit\viewer_live_2026-11-27.html (openen in de browser; ververst zichzelf)
rem Gebruikt door de geplande taak "E314 ochtendopname"; ook met de hand te starten.
rem Let op: deze laptop gebruikt moderne stand-by, waaruit een geplande taak hem NIET wekt.
rem De pc moet dus wakker blijven tot de taak start: wakker.ps1 (zie README).
cd /d "%~dp0"
set TOT=%1
if "%TOT%"=="" set TOT=10:15
set VAN=%2
set TAG=%3
start "MIV-logger" /min cmd /c "C:\Python314\python.exe -u miv_logger.py --tot %TOT% >> data\logger_opname.log 2>&1"
start "VC-logger" /min cmd /c "C:\Python314\python.exe -u vc_logger.py --tot %TOT% >> data\vc_logger_opname.log 2>&1"
if "%TAG%"=="" goto :eof
rem eerst een paar minuten data laten binnenkomen; de run start leeg op VAN min 15 min opwarmtijd
rem (geen "timeout": dat weigert zonder console, zoals in een geplande taak)
ping -n 421 127.0.0.1 > nul
set PYTHONIOENCODING=utf-8
start "Live-run" /min cmd /c "C:\Python314\python.exe -W ignore -u sim_online.py --van %VAN% --tot %TOT% --opwarm 15 --live --tag %TAG% > uit\sim_%TAG%.out 2>&1"
ping -n 91 127.0.0.1 > nul
start "Viewer" /min cmd /c "C:\Python314\python.exe -W ignore -u maak_viewer.py --tag %TAG% --van %VAN% --live --interval 30 > uit\viewer_%TAG%.out 2>&1"
