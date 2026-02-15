@echo off
setlocal
pushd "%~dp0"

echo ========================================
echo  Escolha a frequencia do report:
echo    1^) Semanal
echo    2^) Mensal
echo ========================================
set /p CHOICE=Digite 1 ou 2 e pressione ENTER: 

if "%CHOICE%"=="2" (
    set "FREQ=MENSAL"
) else (
    set "FREQ=SEMANAL"
)

echo.
echo Rodando com FREQ=%FREQ% ...
python report_generator.py %*

popd
endlocal
