param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("gemini", "claude")]
    [string]$Model
)

$models = @{
    "gemini" = "google/gemini-2.5-pro"
    "claude" = "anthropic/claude-opus-4-6"
}
$modelId = $models[$Model]

Write-Host "[1/3] Setting model to $modelId ..." -ForegroundColor Yellow
openclaw models set $modelId

Write-Host "[2/3] Restarting gateway ..." -ForegroundColor Yellow
openclaw gateway restart

Write-Host "[3/3] Verifying ..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
openclaw models status

Write-Host "`nDone! Active model: $modelId" -ForegroundColor Green
