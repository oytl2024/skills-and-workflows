param(
    [Parameter(Mandatory=$true)][string]$BuildRoot,
    [Parameter(Mandatory=$true)][string]$AcceptancePath,
    [string]$PythonExe='python'
)
$ErrorActionPreference='Stop'
$Product=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Output=Join-Path $Product 'output/desktop-application'

function Assert-BuildPath([string]$Path) {
    # Input: local build path. Output: absolute path; reject links or paths outside product output.
    $Full=[IO.Path]::GetFullPath($Path)
    if (-not $Full.StartsWith($Output+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Outside desktop output.' }
    $Item=Get-Item -LiteralPath $Full -Force
    while ($Item -and $Item.FullName -ne $Product) {
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked installation path.' }
        $Item=$Item.Parent
    }
    return $Full
}

$BuildRoot=Assert-BuildPath $BuildRoot
$AcceptancePath=Assert-BuildPath $AcceptancePath
$Proof=Get-Content -LiteralPath $AcceptancePath -Raw | ConvertFrom-Json
$Diagnostics=@(Get-ChildItem -LiteralPath $BuildRoot -Directory | Where-Object {$_.Name.StartsWith('smoke space ')} |
    ForEach-Object {Join-Path $_.FullName 'diagnostics.json'})
$Distributions=@(Get-ChildItem -LiteralPath $BuildRoot -Directory | Where-Object {$_.Name.StartsWith('dist space ')} |
    ForEach-Object {Join-Path $_.FullName 'BrainWorkflow'})
if ($Diagnostics.Count -ne 1 -or $Distributions.Count -ne 1) { throw 'Ambiguous build.' }
$Diagnostic=Get-Content -LiteralPath (Assert-BuildPath $Diagnostics[0]) -Raw | ConvertFrom-Json
$Source=& $PythonExe -c 'from pathlib import Path; from wqb.runtime_revision import source_code_revision; print(source_code_revision(Path("wqb")))'
if ($LASTEXITCODE -ne 0 -or -not $Diagnostic.frozen -or -not $Diagnostic.frontend_ready -or
    -not $Diagnostic.source_identity_valid -or $Source.Trim() -ne $Diagnostic.code_revision -or
    $Proof.source_revision -ne $Source.Trim() -or -not $Proof.passed -or $Proof.native_tests -lt 2) {
    throw 'Current-source native acceptance is required.'
}
$Distribution=Assert-BuildPath $Distributions[0]
$Files=@(Get-ChildItem -LiteralPath $Distribution -Recurse -Force)
if (@($Files | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count) { throw 'Linked bundle.' }
$Installed=Join-Path $Output 'installed'
$Target=Join-Path $Installed 'BrainWorkflow'
$Stage=Join-Path $Installed 'BrainWorkflow.next'
$Previous=Join-Path $Installed 'BrainWorkflow.previous'
if ((Test-Path -LiteralPath $Stage) -or (Test-Path -LiteralPath $Previous)) { throw 'Unfinished installation; inspect first.' }
if (@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq (Join-Path $Target 'BrainWorkflow.exe')}).Count) {
    throw 'Stop the current application before installing.'
}
if (Test-Path -LiteralPath $Target) {
    [void](Assert-BuildPath $Target)
    if (@(Get-ChildItem -LiteralPath $Target -Recurse -Force |
        Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count) { throw 'Linked old bundle.' }
}
Copy-Item -LiteralPath $Distribution -Destination $Stage -Recurse
foreach ($File in $Files | Where-Object {-not $_.PSIsContainer}) {
    $Copy=Join-Path $Stage ([IO.Path]::GetRelativePath($Distribution,$File.FullName))
    if ((Get-FileHash -LiteralPath $Copy).Hash -ne (Get-FileHash -LiteralPath $File.FullName).Hash) { throw 'Bundle copy differs.' }
}
if (Test-Path -LiteralPath $Target) { Move-Item -LiteralPath $Target -Destination $Previous }
try { Move-Item -LiteralPath $Stage -Destination $Target }
catch {
    if (Test-Path -LiteralPath $Previous) { Move-Item -LiteralPath $Previous -Destination $Target }
    throw
}
if (Test-Path -LiteralPath $Previous) {
    [void](Assert-BuildPath $Previous)
    Remove-Item -LiteralPath $Previous -Recurse -Force
}
$Receipt=@{schema_version=1;code_revision=$Source.Trim();
    exe_sha256=(Get-FileHash -LiteralPath (Join-Path $Target 'BrainWorkflow.exe')).Hash.ToLowerInvariant();
    acceptance=$Proof;file_count=@($Files | Where-Object {-not $_.PSIsContainer}).Count}
[IO.File]::WriteAllText((Join-Path $Installed 'installation.json'),
    ($Receipt|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
$Receipt | ConvertTo-Json -Depth 5
