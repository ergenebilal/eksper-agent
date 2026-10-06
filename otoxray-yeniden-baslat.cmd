@echo off
rem otoXray API'sini yeniden baslatir: calisan eskisini kapatir, yenisini bu pencerede acar.
rem Pencereyi kapatmayin; sunucuyu durdurmak icin Ctrl+C.
cd /d "%~dp0"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'arac\.exe.*xray serve' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 1 /nobreak >nul
uv run arac xray serve
