#requires -Version 5.1
<#
.SYNOPSIS
    Test de bout-en-bout du bridge BT vers le M5Stack.

.DESCRIPTION
    Envoie une demande d'approval factice sur le port BT défini par M5STACK_PORT
    (ou un port passé en argument), affiche les pings reçus pendant l'attente,
    et confirme si le M5Stack répond bien à un appui bouton.

    À utiliser AVANT `vibe-m5stack` pour s'assurer que le maillon hardware marche.
    Si ce script passe mais que `vibe-m5stack` ne déclenche pas d'approval,
    le problème est côté Vibe (agent / config / prompt qui ne triggre pas de tool).

.EXAMPLE
    .\test_bt_bridge.ps1
    Utilise $env:M5STACK_PORT.

.EXAMPLE
    .\test_bt_bridge.ps1 -Port COM10
    Force le port.
#>
param(
    [string]$Port = $env:M5STACK_PORT,
    [int]$TimeoutSec = 30
)

if (-not $Port) {
    Write-Error "Aucun port. Set M5STACK_PORT ou passe -Port COMxx."
    exit 1
}

Write-Host "==> Test bridge BT sur $Port" -ForegroundColor Cyan
Write-Host ""

try {
    $sp = New-Object System.IO.Ports.SerialPort $Port, 115200, None, 8, One
    $sp.ReadTimeout = 1000
    $sp.Open()
} catch {
    Write-Error "Impossible d'ouvrir $Port : $($_.Exception.Message)"
    Write-Host "Vérifie le pairing BT et que le M5Stack est sous tension (chat doit danser)." -ForegroundColor Yellow
    exit 1
}

Write-Host "Port ouvert. Envoi d'une demande d'approval factice..." -ForegroundColor Green
$reqId = Get-Random -Minimum 10000 -Maximum 99999
$msg = @{
    type  = "approval"
    id    = $reqId
    title = "[TEST] bridge BT"
    body  = "Si tu vois cet ecran sur le M5Stack,`nappuie A pour valider le test."
} | ConvertTo-Json -Compress
$sp.WriteLine($msg)

Write-Host "Demande envoyee (id=$reqId)." -ForegroundColor Green
Write-Host "Regarde l'ecran du M5Stack : tu dois voir l'ecran d'approval." -ForegroundColor Yellow
Write-Host "Appuie sur A (bouton gauche) pour valider, ou attends $TimeoutSec s." -ForegroundColor Yellow
Write-Host ""

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$buf = ""
$result = $null

while ((Get-Date) -lt $deadline -and -not $result) {
    try {
        $chunk = $sp.ReadExisting()
        if ($chunk) { $buf += $chunk }
    } catch { }

    while ($buf -match "(?s)^(.*?)(`r?`n)(.*)$") {
        $line = $Matches[1].Trim()
        $buf = $Matches[3]
        if (-not $line) { continue }
        try {
            $obj = $line | ConvertFrom-Json -ErrorAction Stop
            if ($obj.type -eq "ping") {
                Write-Host "  [ping recu - M5Stack vivant en BT]" -ForegroundColor DarkGray
            } elseif ($obj.type -eq "response" -and $obj.id -eq $reqId) {
                $result = $obj
                break
            } else {
                Write-Host "  recv: $line" -ForegroundColor DarkGray
            }
        } catch {
            Write-Host "  [non-JSON] $line" -ForegroundColor DarkGray
        }
    }
    Start-Sleep -Milliseconds 80
}

$sp.Close()
Write-Host ""

if ($result) {
    if ($result.cancelled) {
        Write-Host "==> ANNULE par bouton C. Bridge OK." -ForegroundColor Yellow
    } elseif ($result.approved) {
        Write-Host "==> APPROUVE par bouton A. Bridge BT 100% fonctionnel." -ForegroundColor Green
    } else {
        Write-Host "==> REJETE par bouton B. Bridge OK." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Tu peux lancer vibe-m5stack en toute confiance." -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "==> TIMEOUT - pas de reponse en $TimeoutSec s." -ForegroundColor Red
    Write-Host ""
    Write-Host "Si tu n'as vu aucun ecran d'approval sur le M5Stack :" -ForegroundColor Yellow
    Write-Host "  - mauvais COM (essaie l'autre des deux paires BT)" -ForegroundColor Yellow
    Write-Host "  - M5Stack pas en BT mode (re-flash avec USE_BT_SERIAL=1)" -ForegroundColor Yellow
    Write-Host "Si tu as vu l'ecran mais n'as pas appuye, c'est normal." -ForegroundColor Yellow
    exit 2
}
