@echo off
rem Start beide loggers (MIV en Verkeerscentrum) tot de opgegeven tijd, bv.  opname.bat 10:15
rem Gebruikt door de geplande taak "E314 ochtendopname"; ook met de hand te starten.
cd /d "%~dp0"
set TOT=%1
if "%TOT%"=="" set TOT=10:15
start "MIV-logger" /min cmd /c "C:\Python314\python.exe -u miv_logger.py --tot %TOT% >> data\logger_opname.log 2>&1"
start "VC-logger" /min cmd /c "C:\Python314\python.exe -u vc_logger.py --tot %TOT% >> data\vc_logger_opname.log 2>&1"
