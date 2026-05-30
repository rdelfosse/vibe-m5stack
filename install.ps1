@echo off
rem Vibe M5Stack - Install script for Windows
rem Copyright 2026 Romain Delfosse
rem
rem Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
rem
rem     http://www.apache.org/licenses/LICENSE-2.0
rem
rem Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

<#
.SYNOPSIS
    Installe vibe-m5stack et ses dépendances sur Windows.

.DESCRIPTION
    Ce script:
    1. Vérifie et installe uv (si nécessaire)
    2. Installe mistral-vibe avec le plugin vibe-m5stack
    3. Configure le M5Stack via vibe-m5stack setup
    4. Affiche l'URL du web flasher

.EXAMPLE
    .\install.ps1
#>

# Requires PowerShell to be run as a script (not cmd.exe)
if (-not $IsCoreCLR) {
    Write-Host "Ce script doit être exécuté avec PowerShell, pas cmd.exe" -ForegroundColor Red
    Write-Host "Essaie: .\install.ps1" -ForegroundColor Yellow
    exit 1
}

$ErrorActionPreference = "Stop"

function Write-Status {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host "[install] $Message" -ForegroundColor $Color
}

function Write-Step {
    param(
        [int]$Number,
        [string]$Message
    )
    Write-Host "`n === Étape $Number : $Message ===`n" -ForegroundColor Cyan
}

function Test-IsAdmin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Step 0: Welcome
Clear-Host
Write-Host "" -ForegroundColor DarkGray
Write-Host "  ▄████████████████████████████████████████████████▄  " -ForegroundColor Magenta
Write-Host " ██████████████████████████████████████████ ███" -ForegroundColor Magenta
Write-Host "████ ▀███ █████   ██████ █████ ████ ████ ██████ █████ ██" -ForegroundColor Magenta
Write-Host "████   █   ████   ▀███ ███   ████   █   ████   █   ███   █" -ForegroundColor Magenta
Write-Host "████       ████        ███          ████       ████       ███" -ForegroundColor Magenta
Write-Host " ████████████████   █████   █████       █████   ████     ███" -ForegroundColor Magenta
Write-Host "  ▀██████████████ ██████████   ███       █████████   ██████" -ForegroundColor Magenta
Write-Host "                          ███                        ███" -ForegroundColor Magenta
Write-Host "                          ▀▀▀                        ▀▀▀" -ForegroundColor Magenta
Write-Host "" -ForegroundColor DarkGray
Write-Host "  VIBE M5Stack - Installateur" -ForegroundColor White
Write-Host "  =========================" -ForegroundColor DarkGray
Write-Host ""

# Step 1: Check Python
Write-Step -Number 1 -Message "Vérification de Python"

$pythonExe = "python"
if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    $pythonExe = "py"
    if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
        Write-Status "Python non trouvé!" -Color Red
        Write-Host ""
        Write-Host "Télécharge et installe Python 3.10+ depuis:" -ForegroundColor Yellow
        Write-Host "  https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Coche 'Add Python to PATH' pendant l'installation!" -ForegroundColor Yellow
        exit 1
    }
}

$pythonVersion = & $pythonExe --version 2>$null
Write-Status "Python trouvé: $pythonVersion" -Color Green

# Check Python version
$versionMatch = $pythonVersion -match "(\d+)\.(\d+)"
if ($versionMatch) {
    $major = [int]$matches[1]
    $minor = [int]$matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Write-Status "Python 3.10+ requis (trouvé: $pythonVersion)" -Color Red
        exit 1
    }
}

# Step 2: Install uv
Write-Step -Number 2 -Message "Installation de uv"

$uvInstalled = $false
$uvPath = "$env:USERPROFILE\.local\bin\uv.exe"

if (Test-Path $uvPath) {
    Write-Status "uv déjà installé" -Color Green
    $uvInstalled = $true
} else {
    Write-Status "Installation de uv..." -Color Yellow
    try {
        # Download uv installer
        $uvUrl = "https://astral-sh.github.io/uv/install.ps1"
        $installerPath = "$env:TEMP\uv_install.ps1"
        
        Write-Status "Téléchargement de l'installateur uv..." -Color Yellow
        Invoke-WebRequest -Uri $uvUrl -OutFile $installerPath -UseBasicParsing
        
        # Run installer
        Write-Status "Lancement de l'installation..." -Color Yellow
        & $installerPath -NoConfirm -AddToPath
        
        # Refresh PATH
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User")
        
        if (Test-Path $uvPath) {
            Write-Status "uv installé avec succès" -Color Green
            $uvInstalled = $true
        } else {
            Write-Status "Échec de l'installation de uv" -Color Red
            exit 1
        }
    } catch {
        Write-Status "Erreur lors de l'installation de uv: $_" -Color Red
        Write-Host ""
        Write-Host "Tu peux aussi installer uv manuellement depuis:" -ForegroundColor Yellow
        Write-Host "  https://docs.astral.sh/uv/getting-started#installation" -ForegroundColor Cyan
        exit 1
    }
}

# Step 3: Install vibe with vibe-m5stack
Write-Step -Number 3 -Message "Installation de mistral-vibe + vibe-m5stack"

$repoRoot = $PSScriptRoot
if (-not $repoRoot) {
    $repoRoot = Get-Location
}

Write-Status "Installation depuis: $repoRoot" -Color Yellow

try {
    & uv tool install --reinstall mistral-vibe --with-editable $repoRoot --with-executables-from vibe-m5stack
    Write-Status "Installation terminée" -Color Green
} catch {
    Write-Status "Échec de l'installation: $_" -Color Red
    Write-Host ""
    Write-Host "Essaie de lancer manuellement:" -ForegroundColor Yellow
    Write-Host "  uv tool install --reinstall mistral-vibe --with-editable $repoRoot --with-executables-from vibe-m5stack" -ForegroundColor Cyan
    exit 1
}

# Step 4: Setup M5Stack
Write-Step -Number 4 -Message "Configuration du M5Stack"

Write-Status "Détection du port série..." -Color Yellow

try {
    & vibe-m5stack setup
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Status "Configuration échouée (code: $exitCode)" -Color Red
        Write-Host ""
        Write-Host "Si le M5Stack n'est pas détecté:" -ForegroundColor Yellow
        Write-Host "  1. Branche le M5Stack par USB (câble data, pas charge-only)" -ForegroundColor Yellow
        Write-Host "  2. Installe le driver CP210x depuis: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers" -ForegroundColor Yellow
        Write-Host "  3. Relance: vibe-m5stack setup" -ForegroundColor Yellow
    } else {
        Write-Status "Configuration terminée" -Color Green
    }
} catch {
    Write-Status "Erreur lors de la configuration: $_" -Color Red
}

# Step 5: Web flasher info
Write-Step -Number 5 -Message "Web Flasher"

$webFlasherUrl = "https://rdelfosse.github.io/vibe-m5stack/flash/"
Write-Status "Web flasher disponible:" -Color Green
Write-Host "  $webFlasherUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "Ouvre cette URL dans Chrome/Edge pour flasher le firmware" -ForegroundColor Yellow
Write-Host "sans installer PlatformIO." -ForegroundColor Yellow

# Summary
Write-Host "" -ForegroundColor DarkGray
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "  Installation terminée!" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host ""
Write-Host "Pour commencer:" -ForegroundColor Yellow
Write-Host "  1. Flashe le firmware: ouvre $webFlasherUrl dans Chrome" -ForegroundColor Cyan
Write-Host "  2. Branche le M5Stack par USB" -ForegroundColor Cyan
Write-Host "  3. Lance: vibe-m5stack" -ForegroundColor Cyan
Write-Host ""
Write-Host "En cas de problème: vibe-m5stack doctor" -ForegroundColor Yellow
Write-Host ""
