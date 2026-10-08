param(
    [string]$BackupDirectory = "$(Split-Path -Parent $PSScriptRoot)\storage\backups",
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$envFile = Join-Path $backendRoot ".env"
$envValues = @{}
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            $envValues[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
}

$databaseUrl = $env:DATABASE_URL
if (-not $databaseUrl) { $databaseUrl = $envValues["DATABASE_URL"] }
if (-not $databaseUrl) { throw "Set DATABASE_URL or configure it in backend/.env." }
if ($databaseUrl -notmatch '^postgres(?:ql)?(?:\+[^:]*)?://') { throw "DATABASE_URL must point to PostgreSQL." }
if ($RetentionDays -lt 1) { throw "RetentionDays must be at least 1." }
$pgDump = Get-Command "pg_dump" -ErrorAction SilentlyContinue
if (-not $pgDump) { throw "pg_dump was not found. Add the PostgreSQL bin folder to PATH." }

$uriText = $databaseUrl -replace '^postgres(?:ql)?(?:\+[^:]*)?://', 'postgresql://'
$databaseUri = [Uri]$uriText
$userInfo = $databaseUri.UserInfo.Split(@(':'), 2, [System.StringSplitOptions]::None)
$previousPgUser = $env:PGUSER
$previousPgPassword = $env:PGPASSWORD
$env:PGUSER = [Uri]::UnescapeDataString($userInfo[0])
if ($userInfo.Count -gt 1) { $env:PGPASSWORD = [Uri]::UnescapeDataString($userInfo[1]) }
$hostName = $databaseUri.Host
$port = if ($databaseUri.Port -gt 0) { $databaseUri.Port } else { 5432 }
$databaseName = [Uri]::UnescapeDataString($databaseUri.AbsolutePath.TrimStart('/'))
if (-not $databaseName) { throw "DATABASE_URL is missing the database name." }

New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dumpPath = Join-Path $BackupDirectory "quan1-$stamp.dump"
try {
    & $pgDump.Source --host $hostName --port $port --username $env:PGUSER --dbname $databaseName --format custom --no-owner --file $dumpPath
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE." }
} catch {
    if (Test-Path -LiteralPath $dumpPath) { Remove-Item -LiteralPath $dumpPath -Force }
    throw
} finally {
    if ($null -eq $previousPgPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue } else { $env:PGPASSWORD = $previousPgPassword }
    if ($null -eq $previousPgUser) { Remove-Item Env:PGUSER -ErrorAction SilentlyContinue } else { $env:PGUSER = $previousPgUser }
}

$audioDirectory = $envValues["AUDIO_DIRECTORY"]
if (-not $audioDirectory) { $audioDirectory = "storage/audio" }
if (-not [IO.Path]::IsPathRooted($audioDirectory)) { $audioDirectory = Join-Path $backendRoot $audioDirectory }
if (Test-Path -LiteralPath $audioDirectory) {
    $audioFiles = Get-ChildItem -LiteralPath $audioDirectory -File -Recurse
    if ($audioFiles.Count -gt 0) {
        Compress-Archive -Path (Join-Path $audioDirectory "*") -DestinationPath (Join-Path $BackupDirectory "audio-$stamp.zip") -CompressionLevel Optimal
    }
}

$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -LiteralPath $BackupDirectory -File | Where-Object { $_.LastWriteTime -lt $cutoff -and ($_.Name -like "quan1-*.dump" -or $_.Name -like "audio-*.zip") } | Remove-Item -Force
Write-Output "PostgreSQL backup created: $dumpPath"
