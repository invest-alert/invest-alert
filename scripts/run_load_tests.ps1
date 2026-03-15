[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Email = "",
    [string]$Password = "LoadTest123!",
    [int]$Requests = 100,
    [int]$Concurrency = 10,
    [int]$HarvestRequests = 1,
    [int]$HarvestConcurrency = 1,
    [string]$ContextDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$ResultsRoot = "artifacts/loadtest",
    [string]$AbPath = "ab",
    [switch]$SkipHarvest,
    [switch]$SkipStateful,
    [switch]$DisableKeepAlive
)

$ErrorActionPreference = "Stop"

function Get-JsonPayload {
    param([hashtable]$Body)

    return ($Body | ConvertTo-Json -Depth 10 -Compress)
}

function Invoke-JsonApi {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Body,
        [hashtable]$Headers = @{}
    )

    $jsonBody = $null
    if ($Body.Count -gt 0) {
        $jsonBody = Get-JsonPayload -Body $Body
    }

    if ($null -eq $jsonBody) {
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers
    }

    return Invoke-RestMethod `
        -Method $Method `
        -Uri $Uri `
        -Headers $Headers `
        -Body $jsonBody `
        -ContentType "application/json"
}

function Ensure-Command {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Required command '$Name' was not found on PATH."
    }
}

function Write-TextFile {
    param(
        [string]$Path,
        [string]$Content
    )

    Set-Content -Path $Path -Value $Content -NoNewline -Encoding ascii
}

function Run-Ab {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    $outputPath = Join-Path $script:RunDir "$Name.txt"
    Write-Host ""
    Write-Host "Running benchmark: $Name"
    Write-Host "$script:AbPath $($Arguments -join ' ')"

    & $script:AbPath @Arguments 2>&1 | Tee-Object -FilePath $outputPath
}

function New-RunEmail {
    param([string]$Prefix)

    return "$Prefix-$script:RunId@example.com"
}

$BaseUrl = $BaseUrl.TrimEnd("/")
$script:AbPath = $AbPath
$script:RunId = Get-Date -Format "yyyyMMdd-HHmmss"
$script:RunDir = Join-Path $ResultsRoot $script:RunId

if ([string]::IsNullOrWhiteSpace($Email)) {
    $Email = New-RunEmail -Prefix "loadtest"
}

Ensure-Command -Name $AbPath
New-Item -ItemType Directory -Path $script:RunDir -Force | Out-Null

$healthUrl = "$BaseUrl/health"
$apiBase = "$BaseUrl/api/v1"
$headers = @{}

Write-Host "Checking API health at $healthUrl"
$healthResponse = Invoke-RestMethod -Method Get -Uri $healthUrl
if (-not $healthResponse.success) {
    throw "Health check failed. Start the API before running benchmarks."
}

Write-Host "Bootstrapping load-test user $Email"
$registerBody = @{
    email = $Email
    password = $Password
}

try {
    $bootstrapAuth = Invoke-JsonApi -Method Post -Uri "$apiBase/auth/register" -Body $registerBody
}
catch {
    Write-Host "Register did not return 2xx, falling back to login for the benchmark user."
    $bootstrapAuth = Invoke-JsonApi -Method Post -Uri "$apiBase/auth/login" -Body $registerBody
}

$accessToken = $bootstrapAuth.data.access_token
$refreshToken = $bootstrapAuth.data.refresh_token
if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw "Unable to obtain an access token for the benchmark user."
}

$headers["Authorization"] = "Bearer $accessToken"

Write-Host "Ensuring the benchmark user has a real stock for context harvesting"
$watchlistResponse = Invoke-JsonApi -Method Get -Uri "$apiBase/watchlist" -Body @{} -Headers $headers
$watchlistItems = @($watchlistResponse.data)
$baseWatchlistItem = $watchlistItems | Where-Object { $_.symbol -eq "TATA MOTORS" -and $_.exchange -eq "NSE" } | Select-Object -First 1

if ($null -eq $baseWatchlistItem) {
    $baseWatchlistItem = (Invoke-JsonApi `
        -Method Post `
        -Uri "$apiBase/watchlist" `
        -Body @{ symbol = "Tata Motors"; exchange = "NSE" } `
        -Headers $headers).data
}

$refreshPair = (Invoke-JsonApi -Method Post -Uri "$apiBase/auth/login" -Body $registerBody).data
$logoutPair = (Invoke-JsonApi -Method Post -Uri "$apiBase/auth/login" -Body $registerBody).data

$loginJsonPath = Join-Path $script:RunDir "auth-login.json"
$registerJsonPath = Join-Path $script:RunDir "auth-register.json"
$refreshJsonPath = Join-Path $script:RunDir "auth-refresh.json"
$logoutJsonPath = Join-Path $script:RunDir "auth-logout.json"
$watchlistPostJsonPath = Join-Path $script:RunDir "watchlist-post.json"
$tokenFormPath = Join-Path $script:RunDir "auth-token-form.txt"
$emptyJsonPath = Join-Path $script:RunDir "empty.json"

$registerEmail = New-RunEmail -Prefix "register"
$watchlistPostSymbol = "LOADTEST BENCH $script:RunId"

Write-TextFile -Path $loginJsonPath -Content (Get-JsonPayload -Body $registerBody)
Write-TextFile -Path $registerJsonPath -Content (Get-JsonPayload -Body @{
    email = $registerEmail
    password = $Password
})
Write-TextFile -Path $refreshJsonPath -Content (Get-JsonPayload -Body @{
    refresh_token = $refreshPair.refresh_token
})
Write-TextFile -Path $logoutJsonPath -Content (Get-JsonPayload -Body @{
    refresh_token = $logoutPair.refresh_token
})
Write-TextFile -Path $watchlistPostJsonPath -Content (Get-JsonPayload -Body @{
    symbol = $watchlistPostSymbol
    exchange = "NSE"
})
Write-TextFile -Path $tokenFormPath -Content (
    "username=$([uri]::EscapeDataString($Email))&password=$([uri]::EscapeDataString($Password))"
)
Write-TextFile -Path $emptyJsonPath -Content "{}"

$keepAliveArgs = @()
if (-not $DisableKeepAlive) {
    $keepAliveArgs += "-k"
}

$publicArgs = @($keepAliveArgs + @("-n", $Requests, "-c", $Concurrency))
$authArgs = @($keepAliveArgs + @("-n", $Requests, "-c", $Concurrency, "-H", "Authorization: Bearer $accessToken"))
$harvestArgs = @($keepAliveArgs + @("-n", $HarvestRequests, "-c", $HarvestConcurrency, "-H", "Authorization: Bearer $accessToken"))
$statefulArgs = @($keepAliveArgs + @("-n", 1, "-c", 1))
$statefulAuthArgs = @($keepAliveArgs + @("-n", 1, "-c", 1, "-H", "Authorization: Bearer $accessToken"))

Run-Ab -Name "health" -Arguments ($publicArgs + @("$healthUrl"))
Run-Ab -Name "auth-login-json" -Arguments (
    $publicArgs +
    @("-p", $loginJsonPath, "-T", "application/json", "$apiBase/auth/login")
)
Run-Ab -Name "auth-token-form" -Arguments (
    $publicArgs +
    @("-p", $tokenFormPath, "-T", "application/x-www-form-urlencoded", "$apiBase/auth/token")
)
Run-Ab -Name "auth-me" -Arguments ($authArgs + @("$apiBase/auth/me"))
Run-Ab -Name "watchlist-get" -Arguments ($authArgs + @("$apiBase/watchlist"))
Run-Ab -Name "daily-context-get" -Arguments ($authArgs + @("$apiBase/daily-context?date=$ContextDate"))

if (-not $SkipHarvest) {
    Run-Ab -Name "daily-context-harvest" -Arguments (
        $harvestArgs + @("-m", "POST", "-p", $emptyJsonPath, "-T", "application/json", "$apiBase/daily-context/harvest?date=$ContextDate")
    )
}

if (-not $SkipStateful) {
    Run-Ab -Name "auth-register" -Arguments (
        $statefulArgs +
        @("-p", $registerJsonPath, "-T", "application/json", "$apiBase/auth/register")
    )
    Run-Ab -Name "auth-refresh" -Arguments (
        $statefulArgs +
        @("-p", $refreshJsonPath, "-T", "application/json", "$apiBase/auth/refresh")
    )

    Run-Ab -Name "watchlist-post" -Arguments (
        $statefulAuthArgs +
        @("-p", $watchlistPostJsonPath, "-T", "application/json", "$apiBase/watchlist")
    )
    try {
        $watchlistAfterPost = @((Invoke-JsonApi -Method Get -Uri "$apiBase/watchlist" -Body @{} -Headers $headers).data)
        $postBenchmarkItem = $watchlistAfterPost |
            Where-Object { $_.symbol -eq $watchlistPostSymbol -and $_.exchange -eq "NSE" } |
            Select-Object -First 1
        if ($null -ne $postBenchmarkItem) {
            Invoke-RestMethod -Method Delete -Uri "$apiBase/watchlist/$($postBenchmarkItem.id)" -Headers $headers | Out-Null
        }
    }
    catch {
        Write-Host "Watchlist POST cleanup skipped: $($_.Exception.Message)"
    }

    $deleteTarget = (Invoke-JsonApi `
        -Method Post `
        -Uri "$apiBase/watchlist" `
        -Body @{ symbol = "LOADTEST DELETE $script:RunId"; exchange = "NSE" } `
        -Headers $headers).data

    Run-Ab -Name "watchlist-delete" -Arguments (
        $statefulAuthArgs + @("-m", "DELETE", "$apiBase/watchlist/$($deleteTarget.id)")
    )
    Run-Ab -Name "auth-logout" -Arguments (
        $statefulArgs +
        @("-p", $logoutJsonPath, "-T", "application/json", "$apiBase/auth/logout")
    )
}

$notesPath = Join-Path $script:RunDir "run-notes.txt"
@"
Base URL: $BaseUrl
Benchmark user: $Email
Requests: $Requests
Concurrency: $Concurrency
Harvest requests: $HarvestRequests
Harvest concurrency: $HarvestConcurrency
Context date: $ContextDate
Keep-alive enabled: $([bool](-not $DisableKeepAlive))
Skipped harvest: $([bool]$SkipHarvest)
Skipped stateful endpoints: $([bool]$SkipStateful)
"@ | Set-Content -Path $notesPath -Encoding ascii

Write-Host ""
Write-Host "Apache Bench results saved to $script:RunDir"
