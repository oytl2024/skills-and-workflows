param([switch]$Preview, [switch]$FunctionsOnly)

$ErrorActionPreference = 'Stop'
$BuildRetentionDays = 1
$ExcludedCleanupPaths = @(
    '%SystemDrive%', 'skills-and-workflows/BrainWorkflow/%SystemDrive%',
    'skills-and-workflows/BrainWorkflow/output/desktop-build-deps',
    'skills-and-workflows/BrainWorkflow/output/desktop-application/20261125-091347-1980',
    'skills-and-workflows/BrainWorkflow/output/desktop-application/20261125-093958-6717',
    'skills-and-workflows/BrainWorkflow/output/desktop-application/20261125-094407-1915',
    'runs/sandbox-test-4f2b6a075222494eb1c5225febf6f1ed'
)

function Test-ContainedPath($Root, $Path) {
    # Input: absolute strings. Output: bool; only strict descendants qualify.
    return [IO.Path]::GetFullPath($Path).StartsWith([IO.Path]::GetFullPath($Root).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Get-SafeCleanupIdentity($WorkspaceRoot, $Path, $Kind) {
    # Input: root/path/kind strings. Output: identity object or null; reject links, sessions and changed scope.
    $root = [IO.Path]::GetFullPath($WorkspaceRoot)
    $target = [IO.Path]::GetFullPath($Path)
    if (!(Test-ContainedPath $root $target)) { return $null }
    foreach ($excluded in $ExcludedCleanupPaths) {
        $blocked = [IO.Path]::GetFullPath((Join-Path $root $excluded))
        if ($target -eq $blocked -or (Test-ContainedPath $blocked $target) -or (Test-ContainedPath $target $blocked)) { return $null }
    }
    $product = Join-Path $root 'skills-and-workflows/BrainWorkflow'
    if ($Kind -eq 'PythonCache') {
        if ((Split-Path $target -Leaf) -ne '__pycache__') { return $null }
        $allowed = $false
        foreach ($area in @('wqb','tests','scripts')) { if (Test-ContainedPath (Join-Path $product $area) $target) { $allowed = $true } }
        if (!$allowed) { return $null }
    } elseif ($Kind -eq 'OldBuild') {
        if ((Split-Path $target -Parent) -ne (Join-Path $product 'output/desktop-application')) { return $null }
        if ((Split-Path $target -Leaf) -notmatch '^\d{8}-\d{6}-\d+$') { return $null }
        if (!(Test-Path -LiteralPath (Join-Path $target 'input-manifest.json') -PathType Leaf) -or !(Test-Path -LiteralPath (Join-Path $target 'source/wqb') -PathType Container)) { return $null }
        if ((Get-Item -LiteralPath $target).LastWriteTimeUtc -gt [DateTime]::UtcNow.AddDays(-$BuildRetentionDays)) { return $null }
        try {
            $installed = Join-Path $product 'output/desktop-application/installed'
            $receipt = Get-Content -LiteralPath (Join-Path $installed 'installation.json') -Raw | ConvertFrom-Json
            $proof = Get-Content -LiteralPath (Join-Path $installed 'acceptance.json') -Raw | ConvertFrom-Json
            $hash = (Get-FileHash -LiteralPath (Join-Path $installed 'BrainWorkflow/BrainWorkflow.exe') -Algorithm SHA256).Hash
            if (!$proof.passed -or !$receipt.code_revision -or $proof.source_revision -ne $receipt.code_revision -or $hash -ne $receipt.exe_sha256) { return $null }
        } catch { return $null }
    } else { return $null }
    if (!(Test-Path -LiteralPath $target -PathType Container)) { return $null }
    $ancestor = Get-Item -LiteralPath $target
    while ($null -ne $ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $null }
        $ancestor = $ancestor.Parent
    }
    $items = [Collections.Generic.List[object]]::new()
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($target)
    while ($pending.Count) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $null }
            if ($item.Name -match '^(browser|webview2|EBWebView|User Data|profiles?|\.codex|\.obsidian|\.env(?:\..*)?|credentials\.json|auth\.json|Cookies|Login Data|Local State)$') { return $null }
            if ($Kind -eq 'PythonCache' -and ($item.PSIsContainer -or $item.Extension -notin @('.pyc','.pyo'))) { return $null }
            $items.Add($item)
            if ($item.PSIsContainer) { $pending.Push($item.FullName) }
        }
    }
    $lines = @($items | Sort-Object FullName | ForEach-Object { '{0}|{1}|{2}' -f $_.FullName,$_.Length,$_.LastWriteTimeUtc.Ticks })
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $signature = [Convert]::ToHexString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($lines -join "`n")))) } finally { $sha.Dispose() }
    return [pscustomobject]@{ Path=$target; Kind=$Kind; Bytes=($items | Where-Object {!$_.PSIsContainer} | Measure-Object Length -Sum).Sum; Signature=$signature }
}

function Get-TempCleanupPlan($WorkspaceRoot) {
    # Input: workspace string. Output: immutable preview object; never deletes or reads file contents.
    $root = [IO.Path]::GetFullPath($WorkspaceRoot)
    $product = Join-Path $root 'skills-and-workflows/BrainWorkflow'
    if (!(Test-Path -LiteralPath (Join-Path $root 'AGENTS.md')) -or !(Test-Path -LiteralPath (Join-Path $product 'wqb'))) { throw 'Not a BrainWorkflow workspace.' }
    $candidates = [Collections.Generic.List[object]]::new()
    foreach ($area in @('wqb','tests','scripts')) {
        $pending = [Collections.Generic.Stack[string]]::new()
        $pending.Push((Join-Path $product $area))
        while ($pending.Count) {
            foreach ($dir in Get-ChildItem -LiteralPath $pending.Pop() -Directory -Force) {
                if ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
                if ($dir.Name -eq '__pycache__') {
                    $identity = Get-SafeCleanupIdentity $root $dir.FullName 'PythonCache'
                    if ($identity) { $candidates.Add($identity) }
                } else { $pending.Push($dir.FullName) }
            }
        }
    }
    $builds = Join-Path $product 'output/desktop-application'
    if (Test-Path -LiteralPath $builds) {
        foreach ($dir in Get-ChildItem -LiteralPath $builds -Directory -Force) {
            $identity = Get-SafeCleanupIdentity $root $dir.FullName 'OldBuild'
            if ($identity) { $candidates.Add($identity) }
        }
    }
    return [pscustomobject]@{ WorkspaceRoot=$root; Candidates=@($candidates.ToArray()); Bytes=($candidates | Measure-Object Bytes -Sum).Sum }
}

function Invoke-TempCleanupPlan($WorkspaceRoot, $Plan) {
    # Input: workspace string and prior preview. Output: counts; re-audit each candidate and skip busy/changed files.
    if ([IO.Path]::GetFullPath($WorkspaceRoot) -ne $Plan.WorkspaceRoot) { throw 'Workspace changed.' }
    $deleted = 0; $freed = 0; $skipped = [Collections.Generic.List[string]]::new()
    foreach ($candidate in $Plan.Candidates) {
        try {
            $current = Get-SafeCleanupIdentity $WorkspaceRoot $candidate.Path $candidate.Kind
            if (!$current -or $current.Signature -ne $candidate.Signature) { throw 'Preview changed or protected.' }
            foreach ($process in Get-CimInstance Win32_Process -ErrorAction Stop) {
                if ($process.ExecutablePath -and (Test-ContainedPath $current.Path $process.ExecutablePath)) { throw 'Build process is running.' }
            }
            foreach ($file in Get-ChildItem -LiteralPath $current.Path -File -Recurse -Force) {
                $stream = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
                $stream.Dispose()
            }
            $check = Get-SafeCleanupIdentity $WorkspaceRoot $candidate.Path $candidate.Kind
            if (!$check -or $check.Signature -ne $candidate.Signature) { throw 'Contents changed.' }
            Remove-Item -LiteralPath $current.Path -Recurse -ErrorAction Stop
            $deleted++; $freed += $current.Bytes
        } catch { $skipped.Add($candidate.Path + ': ' + $_.Exception.Message) }
    }
    return [pscustomobject]@{ DeletedCount=$deleted; FreedBytes=$freed; Skipped=@($skipped.ToArray()) }
}

if ($FunctionsOnly) { return }
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$plan = Get-TempCleanupPlan $workspace
Write-Host 'BrainWorkflow temporary-file cleanup / 临时文件清理'
Write-Host 'Preserved: knowledge, runs, sessions, installed app, config and Git.'
$plan.Candidates | Select-Object Path,Kind,@{n='MB';e={[Math]::Round($_.Bytes/1MB,2)}} | Format-Table -AutoSize -Wrap
Write-Host ('Candidates: {0}; estimated {1:N2} MB' -f $plan.Candidates.Count,($plan.Bytes/1MB))
if ($Preview -or !$plan.Candidates.Count) { return }
if ((Read-Host 'Type Y to permanently delete ONLY listed paths / 输入 Y 确认') -cne 'Y') { Write-Host 'Cancelled / 已取消'; return }
Invoke-TempCleanupPlan $workspace $plan | Format-List
