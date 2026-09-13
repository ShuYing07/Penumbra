# -*- coding: utf-8 -*-
# One-time setup for training venv (Python 3.11 + LLaMA-Factory + QLoRA stack)
# Does NOT pollute main venv (D:\StockAIPredictor\venv, Python 3.14, for packaging)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\bootstrap_venv_train.ps1
$ErrorActionPreference = "Stop"

$PROJECT = "D:\StockAIPredictor"
$VENV = Join-Path $PROJECT "venv_train"
$PY = Join-Path $VENV "Scripts\python.exe"
$LF = Join-Path $VENV "Scripts\llamafactory-cli.exe"
$TUNA = "https://pypi.tuna.tsinghua.edu.cn/simple"

Write-Host "=== StockAIPredictor Training Environment Setup ===" -ForegroundColor Cyan

# 1. Find Python 3.11
$pyExe = $null
$userPy311 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
foreach ($cand in @("py", "python3.11", "C:\Python311\python.exe", "C:\Program Files\Python311\python.exe", $userPy311)) {
    try {
        $ver = & $cand --version 2>$null
        if ($ver -match "3\.11") { $pyExe = $cand; break }
    } catch { }
}
if (-not $pyExe) {
    Write-Host "Python 3.11 not found. LLaMA-Factory requires 3.9-3.11; main venv 3.14 is incompatible." -ForegroundColor Red
    Write-Host "Install Python 3.11.x from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}
Write-Host "[1/4] Python 3.11 ready: $pyExe" -ForegroundColor Green

# 2. Create venv
if (Test-Path $VENV) {
    Write-Host "[2/4] venv_train already exists, skip: $VENV" -ForegroundColor Yellow
} else {
    & $pyExe -m venv $VENV
    if ($LASTEXITCODE -ne 0) { Write-Host "venv creation failed" -ForegroundColor Red; exit 1 }
    Write-Host "[2/4] venv_train created: $VENV" -ForegroundColor Green
}

# 3. Upgrade pip
& $PY -m pip install -U pip -i $TUNA

# 4. Install torch (CUDA 12.8 for Blackwell RTX 50-series) + training stack
Write-Host "[3/4] Installing torch (CUDA 12.8, ~2.5GB, please wait)..." -ForegroundColor Cyan
& $PY -m pip install torch --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) {
    Write-Host "cu128 unavailable, falling back to default PyTorch (latest CUDA)..." -ForegroundColor Yellow
    & $PY -m pip install torch
    if ($LASTEXITCODE -ne 0) { Write-Host "torch install failed" -ForegroundColor Red; exit 1 }
}

Write-Host "[3/4] Installing training stack (transformers/peft/trl/llamafactory)..." -ForegroundColor Cyan
& $PY -m pip install `
    "transformers>=4.45,<5.0" "peft>=0.13" "trl>=0.11" accelerate `
    bitsandbytes sentencepiece datasets "llamafactory>=0.9" `
    -i $TUNA
if ($LASTEXITCODE -ne 0) { Write-Host "training stack install failed" -ForegroundColor Red; exit 1 }

# 5. Self-check
Write-Host "[4/4] Self-check..." -ForegroundColor Cyan
& $PY -c "import torch; print('  torch', torch.__version__); print('  CUDA available:', torch.cuda.is_available()); print('  Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
if ($LASTEXITCODE -ne 0) { Write-Host "torch self-check failed" -ForegroundColor Red; exit 1 }
& $LF version
if ($LASTEXITCODE -ne 0) { Write-Host "llamafactory-cli not available" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== Training Environment Ready ===" -ForegroundColor Green
Write-Host "venv_train: $VENV" -ForegroundColor Green
Write-Host "Train cmd: $LF train training_configs\qwen2_5_qlora_curriculum.yaml" -ForegroundColor Cyan
Write-Host "(First run downloads Qwen2.5-7B-Instruct fp16 ~15GB via HF mirror)" -ForegroundColor Yellow
