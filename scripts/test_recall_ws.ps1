# scripts\test_recall_ws.ps1
# Recall.ai WS end-to-end test — PowerShell version of test_recall_ws.sh
#
# Usage:
#   .\scripts\test_recall_ws.ps1 "https://teams.live.com/meet/xxx?p=yyy"

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$MeetingUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Validate URL ───────────────────────────────────────────────────────────────
if ($MeetingUrl -notmatch '^https://teams\.(microsoft|live)\.com/') {
    Write-Error "MeetingUrl must start with https://teams.microsoft.com/ or https://teams.live.com/"
    exit 1
}

# ── Load .env ─────────────────────────────────────────────────────────────────
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Error ".env not found at $EnvFile"
    exit 1
}

$env_vars = @{}
foreach ($line in (Get-Content $EnvFile)) {
    # skip blank lines and comments
    if ($line -match '^\s*$' -or $line -match '^\s*#') { continue }
    if ($line -match '^([^=]+)=(.*)$') {
        $key   = $Matches[1].Trim()
        $value = $Matches[2].Trim() -replace '\s+#.*$', ''  # strip inline comments
        $env_vars[$key] = $value
        [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

# ── Required vars ─────────────────────────────────────────────────────────────
$RecallApiKey     = $env_vars["RECALL_API_KEY"]
$RecallRegion     = if ($env_vars.ContainsKey("RECALL_REGION")) { $env_vars["RECALL_REGION"] } else { "ap-northeast-1" }
$CosmosEndpoint   = $env_vars["AZURE_COSMOS_ENDPOINT"]
$CosmosKey        = $env_vars["AZURE_COSMOS_KEY"]
$CosmosDatabase   = if ($env_vars.ContainsKey("COSMOS_DATABASE")) { $env_vars["COSMOS_DATABASE"] } else { "meeting_db" }
$RgName           = if ($env_vars.ContainsKey("RG_NAME")) { $env_vars["RG_NAME"] } else { "rg-mochi-kiki" }
$AppName          = if ($env_vars.ContainsKey("APP_NAME")) { $env_vars["APP_NAME"] } else { "mochikiki-bot-dev" }

foreach ($v in @("RECALL_API_KEY","AZURE_COSMOS_ENDPOINT","AZURE_COSMOS_KEY")) {
    if (-not $env_vars.ContainsKey($v) -or [string]::IsNullOrWhiteSpace($env_vars[$v])) {
        Write-Error ".env is missing $v"
        exit 1
    }
}

# ── Get Container App FQDN ────────────────────────────────────────────────────
Write-Host "Getting Container App FQDN..."
$Fqdn = (az containerapp show -n $AppName -g $RgName --query "properties.configuration.ingress.fqdn" -o tsv 2>&1)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Fqdn)) {
    Write-Error "Could not get FQDN for $AppName. Make sure 'az login' is done and the app exists."
    exit 1
}
$WsUrl      = "wss://$Fqdn/api/recall/ws"
$RecallBase = "https://$RecallRegion.recall.ai"

Write-Host ""
Write-Host "════════════════════════════════════════════════════════"
Write-Host "Recall.ai WS E2E Test"
Write-Host "════════════════════════════════════════════════════════"
Write-Host "  Meeting URL  : $MeetingUrl"
Write-Host "  WS endpoint  : $WsUrl"
Write-Host "  Recall region: $RecallRegion  ($RecallBase)"
Write-Host "  Cosmos DB    : $CosmosDatabase"
Write-Host "════════════════════════════════════════════════════════"
Write-Host ""
Read-Host "Send Recall.ai bot to the meeting? Press Enter to continue (Ctrl-C to cancel)"

# ── 1) Create Recall bot ──────────────────────────────────────────────────────
Write-Host "::: 1. Creating Recall bot..."

$Body = @{
    meeting_url = $MeetingUrl
    bot_name    = "MOCHI-kiki-test"
    recording_config = @{
        transcript = @{
            provider = @{
                recallai_streaming = @{
                    language_code = "ja"
                    mode          = "prioritize_accuracy"
                }
            }
        }
        audio_mixed_raw = @{}
        realtime_endpoints = @(
            @{
                type   = "websocket"
                url    = $WsUrl
                events = @("audio_mixed_raw.data", "transcript.data")
            }
        )
    }
} | ConvertTo-Json -Depth 10

try {
    $Response = Invoke-RestMethod `
        -Method POST `
        -Uri "$RecallBase/api/v1/bot" `
        -Headers @{ "Authorization" = "Token $RecallApiKey"; "Content-Type" = "application/json" } `
        -Body $Body
} catch {
    Write-Host "❌ Bot creation failed:"
    Write-Host $_.Exception.Response
    $stream = $_.Exception.Response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    Write-Host $reader.ReadToEnd()
    exit 1
}

$BotId = $Response.id
if ([string]::IsNullOrWhiteSpace($BotId)) {
    Write-Host "❌ Bot creation failed — no id in response:"
    $Response | ConvertTo-Json
    exit 1
}
Write-Host "✓ Bot ID: $BotId"

# ── 2) Upsert Cosmos meetings record ─────────────────────────────────────────
$TestMeetingId = "test-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
Write-Host "::: 2. Upserting Cosmos meetings record (id=$TestMeetingId)..."

$PyScript = @"
import asyncio, os
from datetime import datetime, timezone
from azure.cosmos.aio import CosmosClient

async def main():
    client = CosmosClient(os.environ['AZURE_COSMOS_ENDPOINT'], credential=os.environ['AZURE_COSMOS_KEY'])
    db = client.get_database_client(os.environ.get('COSMOS_DATABASE', 'meeting_db'))
    c = db.get_container_client('meetings')
    doc = {
        'id': os.environ['_MEETING_ID'],
        'thread_id': 'test-thread',
        'organizer_id': 'test-organizer',
        'started_at': datetime.now(tz=timezone.utc).isoformat(),
        'ended_at': None,
        'transcript_subscription_id': None,
        'recall_bot_id': os.environ['_BOT_ID'],
        'transcript_source': 'recall',
    }
    await c.upsert_item(doc)
    print(f"Upserted: id={doc['id']}  recall_bot_id={doc['recall_bot_id']}")
    await client.close()

asyncio.run(main())
"@

$env:_MEETING_ID = $TestMeetingId
$env:_BOT_ID     = $BotId

$PyScript | python -
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Cosmos upsert failed. The bot is created (BOT_ID=$BotId) but the server won't resolve it."
    Write-Host "   Wait up to 90 sec — Recall retries 30x. Or re-run the script."
    exit 1
}

Write-Host ""
Write-Host "════════════════════════════════════════════════════════"
Write-Host "✅ Done — bot is joining the meeting"
Write-Host "════════════════════════════════════════════════════════"
Write-Host ""
Write-Host "▼ Stream logs in another terminal:"
Write-Host "    az containerapp logs show -n $AppName -g $RgName --follow"
Write-Host ""
Write-Host "▼ Stop the bot when done:"
Write-Host "    Invoke-RestMethod -Method POST -Uri '$RecallBase/api/v1/bot/$BotId/leave_call/' -Headers @{ 'Authorization' = 'Token $RecallApiKey' }"
Write-Host ""
Write-Host "  BOT_ID         = $BotId"
Write-Host "  TEST_MEETING_ID = $TestMeetingId"
