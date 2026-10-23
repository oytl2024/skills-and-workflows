param(
    [string]$PythonExe = (Get-Command python -ErrorAction Stop).Source,
    [string]$DependencyRoot = "",
    [string]$FrontendDist = ""
)
$ErrorActionPreference = "Stop"
$WorkflowRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$OutputRoot = Join-Path $WorkflowRoot "output/desktop-application"
if (-not $DependencyRoot) { $DependencyRoot = Join-Path $WorkflowRoot "output/desktop-build-deps/python" }
if (-not $FrontendDist) { $FrontendDist = Join-Path $WorkflowRoot "frontend/dist" }
$DependencyRoot = [IO.Path]::GetFullPath($DependencyRoot)
$FrontendDist = [IO.Path]::GetFullPath($FrontendDist)
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDist "index.html") -PathType Leaf)) {
    throw "Frontend owner must build frontend/dist/index.html first; no frontend files were changed."
}
# Inputs are explicit product/dependency boundaries, never workspace data/config trees.
foreach ($Path in @($DependencyRoot, $FrontendDist)) {
    if (-not $Path.StartsWith($WorkflowRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build inputs must remain inside the workflow workspace."
    }
    $Item = Get-Item -LiteralPath $Path
    if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Build input cannot be a link/junction." }
}
$BuildRoot = Join-Path $OutputRoot (Get-Date -Format "yyyyMMdd-HHmmss-ffff")
$Distribution = Join-Path $BuildRoot ("dist space " + [char]0x4e2d + [char]0x6587)
$Stage = Join-Path $BuildRoot "source"
New-Item -ItemType Directory -Path (Join-Path $Stage "wqb"), (Join-Path $Stage "scripts"), (Join-Path $Stage "frontend/dist") -Force | Out-Null
# Keep generated packages local without editing the parent's shared ignore rules.
Set-Content -LiteralPath (Join-Path $OutputRoot ".gitignore") -Value "*" -Encoding ascii
$Manifest = @()
foreach ($Boundary in @(@{ Source = (Join-Path $WorkflowRoot "wqb"); Target = "wqb"; PythonOnly = $true },
                        @{ Source = $FrontendDist; Target = "frontend/dist"; PythonOnly = $false })) {
    $Source = [IO.Path]::GetFullPath($Boundary.Source)
    $Items = Get-ChildItem -LiteralPath $Source -Recurse -Force
    foreach ($Item in $Items) {
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked build input rejected." }
        if ($Item.PSIsContainer) { continue }
        if ($Boundary.PythonOnly -and $Item.Extension -ne ".py") { continue }
        $Relative = [IO.Path]::GetRelativePath($Source, $Item.FullName)
        if (-not $Boundary.PythonOnly -and ($Item.Extension -notin @(".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".svg", ".woff", ".woff2", ".ttf"))) {
            throw "Unexpected frontend artifact; only compiled web assets may enter bundle: $Relative"
        }
        $TargetRelative = Join-Path $Boundary.Target $Relative
        $Target = Join-Path $Stage $TargetRelative
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($Target)) -Force | Out-Null
        Copy-Item -LiteralPath $Item.FullName -Destination $Target
        $Manifest += @{ path = $TargetRelative; sha256 = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash }
    }
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "desktop_entry.py") -Destination (Join-Path $Stage "scripts/desktop_entry.py")
ConvertTo-Json -InputObject $Manifest -Depth 4 | Set-Content -LiteralPath (Join-Path $BuildRoot "input-manifest.json") -Encoding utf8
$PreviousPythonPath = $env:PYTHONPATH
$PreviousTemp = $env:TEMP
$PreviousTmp = $env:TMP
try {
    $env:PYTHONPATH = $DependencyRoot
    $env:SystemRoot = [Environment]::GetFolderPath("Windows")
    $env:windir = $env:SystemRoot
    $env:TEMP = Join-Path $BuildRoot "temp"
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
    $Arguments = @("-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--noupx",
        "--name", "BrainWorkflow", "--distpath", $Distribution,
        "--workpath", (Join-Path $BuildRoot "work"), "--specpath", $BuildRoot,
        "--paths", $Stage, "--paths", $DependencyRoot,
        "--add-data", ((Join-Path $Stage "wqb") + ";wqb"),
        "--add-data", ((Join-Path $Stage "frontend/dist") + ";frontend/dist"),
        "--collect-submodules", "wqb", "--collect-all", "webview",
        "--collect-all", "pythonnet", "--collect-all", "clr_loader",
        "--hidden-import", "webview.platforms.edgechromium",
        "--exclude-module", "PyQt5", "--exclude-module", "PyQt6",
        "--exclude-module", "PySide2", "--exclude-module", "PySide6",
        "--exclude-module", "gi", "--exclude-module", "cefpython3",
        (Join-Path $Stage "scripts/desktop_entry.py"))
    Push-Location $Stage
    try {
        & $PythonExe @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $BuildRoot "build.log")
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)." }
    } finally { Pop-Location }
    $Exe = Join-Path $Distribution "BrainWorkflow/BrainWorkflow.exe"
    $SmokeRoot = Join-Path $BuildRoot ("smoke space " + [char]0x4e2d + [char]0x6587)
    New-Item -ItemType Directory -Path $SmokeRoot | Out-Null
    $Diagnostics = Join-Path $SmokeRoot "diagnostics.json"
    $Process = Start-Process -FilePath $Exe -ArgumentList @("--self-test", "--diagnostics-output", ('"' + $Diagnostics + '"')) -WindowStyle Hidden -PassThru
    if (-not $Process.WaitForExit(30000)) { throw "Packaged self-test timed out; inspect process before retrying." }
    if ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Diagnostics)) { throw "Packaged self-test failed." }
    $Result = Get-Content -LiteralPath $Diagnostics -Raw | ConvertFrom-Json
    if (-not $Result.frozen -or -not $Result.frontend_ready -or -not $Result.source_identity_valid -or $Result.backend_started) {
        throw "Packaged self-test contract failed."
    }
    $SourceRevision = & $PythonExe -c "from pathlib import Path; from wqb.runtime_revision import source_code_revision; import sys; print(source_code_revision(Path(sys.argv[1])))" (Join-Path $Stage "wqb")
    if ($LASTEXITCODE -ne 0 -or $Result.code_revision -ne $SourceRevision.Trim()) {
        throw "Packaged revision does not match the exact staged source snapshot."
    }
    $Worker = Start-Process -FilePath $Exe -ArgumentList @("--worker-module", "wqb.cli", "--help") -WindowStyle Hidden -PassThru
    if (-not $Worker.WaitForExit(30000)) { throw "Packaged offline worker import smoke timed out." }
    if ($Worker.ExitCode -ne 0) { throw "Packaged CLI worker import smoke failed." }
    Write-Output "EXE: $Exe"
    Write-Output "Packaged offline diagnostics: $Diagnostics"
    Write-Output "UI/backend fixture smoke remains a separate acceptance step; no real data roots were opened."
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:TEMP = $PreviousTemp
    $env:TMP = $PreviousTmp
}
