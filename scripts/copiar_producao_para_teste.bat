@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."

echo.
echo ============================================
echo  Copiar Sistema_Avaliacao: PRODUCAO -^> TESTE
echo ============================================
echo.
echo Isso apaga o conteudo atual da planilha de TESTE
echo e cola uma copia da PRODUCAO (mesmo ID de teste).
echo A planilha de frequencia NAO e alterada.
echo.
set /p OK="Continuar? (S/N): "
if /I not "%OK%"=="S" (
    echo Cancelado.
    goto :fim
)

echo.
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

echo Copiando...
%PY% "scripts\copiar_producao_para_teste.py" --confirmar
if errorlevel 1 goto :erro

echo.
echo Conferindo nomes das abas...
%PY% "scripts\copiar_producao_para_teste.py" --corrigir-nomes
if errorlevel 1 goto :erro

echo.
echo Pronto. Recarregue o app local se ele ja estiver aberto.
goto :fim

:erro
echo.
echo A copia falhou. Veja a mensagem acima.

:fim
echo.
pause
endlocal
