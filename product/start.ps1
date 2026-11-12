param([switch]$Https, [switch]$SkipContestImport)
$ErrorActionPreference = 'Stop'
$previousEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Push-Location $PSScriptRoot
try {
    if (!(Test-Path -LiteralPath '.env')) {
        if (Test-Path -LiteralPath '.env.example') {
            # New install: start from .env.example so the documented demo passwords (u001/u002) are kept;
            # only the empty infrastructure secrets below get random values. Existing .env files are never rewritten.
            $generated = 'DB_PASSWORD', 'AGENT_TOKEN', 'ALPHA_PASSWORD', 'BETA_PASSWORD', 'IMPORT_TOKEN', 'S3_PASSWORD'
            Get-Content -LiteralPath '.env.example' | ForEach-Object {
                if ($_ -match '^PRODUCT_(\w+)=\s*$' -and $generated -contains $Matches[1]) {
                    "PRODUCT_$($Matches[1])=" + [guid]::NewGuid().ToString('N')
                } else { $_ }
            } | Set-Content -LiteralPath '.env' -Encoding ascii
        } else {
            'DB_PASSWORD', 'AGENT_TOKEN', 'ALPHA_PASSWORD', 'BETA_PASSWORD' | ForEach-Object {
                "PRODUCT_$_=" + [guid]::NewGuid().ToString('N')
            } | Set-Content -LiteralPath '.env' -Encoding ascii
        }
    }
    foreach ($setting in 'IMPORT_TOKEN', 'S3_PASSWORD') {
        if (!(Select-String -LiteralPath '.env' -Pattern "^PRODUCT_${setting}=" -Quiet)) {
            "PRODUCT_${setting}=" + [guid]::NewGuid().ToString('N') | Add-Content -LiteralPath '.env' -Encoding ascii
        }
    }
    foreach ($setting in 'MODEL_BASE_URL', 'MODEL_NAME', 'MODEL_API_KEY') {
        if (!(Select-String -LiteralPath '.env' -Pattern "^PRODUCT_${setting}=" -Quiet)) {
            "PRODUCT_$setting=" | Add-Content -LiteralPath '.env' -Encoding ascii
        }
    }
    # Model settings: only names are printed, never values.
    $model = @{}
    Get-Content -LiteralPath '.env' | ForEach-Object {
        if ($_ -match '^PRODUCT_(MODEL_BASE_URL|MODEL_NAME|MODEL_API_KEY)=(.*)$') { $model[$Matches[1]] = $Matches[2].Trim() }
    }
    $missing = @('MODEL_BASE_URL', 'MODEL_NAME', 'MODEL_API_KEY' | Where-Object { !$model[$_] } | ForEach-Object { "PRODUCT_$_" })
    if ($missing.Count -gt 0) {
        Write-Host "Chat (model answers) needs $($missing -join ', ') in product/.env; login, data and rules work without it."
    }
    $composeFiles = @('-f', 'compose.yaml')
    if ($Https) {
        & (Join-Path $PSScriptRoot 'tls/generate-local.ps1')
        $composeFiles += @('-f', 'compose.https.yaml')
    }
    docker compose @composeFiles up --build --remove-orphans --wait --wait-timeout 120
    if ($LASTEXITCODE -ne 0) { throw 'Product startup failed. Check the Compose output.' }

    if (!$SkipContestImport) {
        # Official v1.1.0 sample data (product/data/contest). Runs inside the importer image, so only Docker is needed.
        # Check first; import only missing rows (never overwrites edited purpose/note), then check again.
        # --allow-main: this script is the owner's explicit start of their own instance; manual runs keep the guard.
        $importer = @('compose') + $composeFiles + @('run', '--rm', '--no-deps', '-T', '-v', "${PSScriptRoot}:/work",
            '--entrypoint', 'python', 'importer', '/work/import_contest_data.py', '--direct-db', '--allow-main')
        & docker @importer --check-only
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Contest data missing or incomplete, importing...'
            & docker @importer
            if ($LASTEXITCODE -ne 0) { throw 'Contest data import failed. See the importer output above.' }
            & docker @importer --check-only
            if ($LASTEXITCODE -ne 0) { throw 'Contest data check failed after import. See the importer output above.' }
        }
        Write-Host '赛题数据就绪：40 张发票、48 条流水'
    }
} finally {
    Pop-Location
    [Console]::OutputEncoding = $previousEncoding
}
