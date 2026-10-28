@echo off
rem The app on a Windows PC for trying it out: the built UI from frontend\dist, data in
rem backend\data-dev, Tesseract from its Windows installer. npm run build first.
setlocal
set ROOT=%~dp0..
set DATA_DIR=%ROOT%\backend\data-dev
set STATIC_DIR=%ROOT%\frontend\dist
set MODEL_CACHE=%ROOT%\backend\.models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PATH=C:\Program Files\Tesseract-OCR;%PATH%
cd /d "%ROOT%\backend"
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8491
