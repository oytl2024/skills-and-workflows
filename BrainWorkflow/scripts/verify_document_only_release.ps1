param([switch]$SelfTest,
      [string]$PythonExe = '',
      [string]$BaseStem = '',
      [string]$ResultStem = '')
$ErrorActionPreference = 'Stop'
$RegisteredFailure = 'test_todo_owns_mainline_and_latest_handoff (tests.test_project_entry_docs.ProjectEntryDocsTests.test_todo_owns_mainline_and_latest_handoff)'
$MaximumReceiptBytes = 65536
$MaximumLogBytes = 16 * 1024 * 1024

function Get-BytesDigest([byte[]]$Bytes) {
    # Input: consumed bytes. Output: lowercase SHA256 str, independent of later path contents.
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

function Read-Evidence([string]$Path, [long]$Limit) {
    # Input: bounded regular-file path. Output: exact bytes/hash plus held read handle; no write/delete sharing.
    $Item = Get-Item -LiteralPath $Path -Force
    if ($Item.PSIsContainer -or ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe evidence file.' }
    $Stream = [IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $Memory = [IO.MemoryStream]::new()
    try {
        if ($Stream.Length -gt $Limit) { throw 'Evidence byte bound exceeded.' }
        $Stream.CopyTo($Memory)
        $Bytes = $Memory.ToArray()
        return @{bytes=$Bytes;sha256=(Get-BytesDigest $Bytes);handle=$Stream}
    } catch { $Stream.Dispose(); throw } finally { $Memory.Dispose() }
}

function Assert-EvidenceUnchanged([string]$Path, [string]$ExpectedDigest) {
    # Input: consumed path/hash. Output: None; refuse path replacement before publishing acceptance.
    $Current = Read-Evidence $Path $MaximumLogBytes
    try {
        if ($Current.sha256 -cne $ExpectedDigest) { throw 'Consumed evidence changed.' }
    } finally { $Current.handle.Dispose() }
}

function Write-EvidenceExclusive([string]$Path, [byte[]]$Bytes) {
    # Input: new evidence path/bytes. Output: None; existing entries must not be overwritten.
    $Stream = [IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $Stream.Write($Bytes,0,$Bytes.Length); $Stream.Flush($true) } finally { $Stream.Dispose() }
}

function Invoke-EvidenceSelfTests {
    # Input: none. Output: filesystem case count int; operate only on owned synthetic temporary files.
    $Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../output/desktop-validation'))
    $Probe = Get-Item -LiteralPath $Root
    while ($null -ne $Probe) {
        if ($Probe.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked test root.' }
        $Probe = $Probe.Parent
    }
    $Sandbox = Join-Path $Root ('document-proof-selftest-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $Sandbox) { throw 'Test sandbox already exists.' }
    [IO.Directory]::CreateDirectory($Sandbox) | Out-Null
    try {
        $Path = Join-Path $Sandbox 'once.bin'
        $Original = [Text.Encoding]::UTF8.GetBytes('original')
        Write-EvidenceExclusive $Path $Original
        $Rejected = $false
        try { Write-EvidenceExclusive $Path ([Text.Encoding]::UTF8.GetBytes('replacement')) } catch [IO.IOException] { $Rejected = $true }
        if (-not $Rejected -or (Get-BytesDigest ([IO.File]::ReadAllBytes($Path))) -cne (Get-BytesDigest $Original)) {
            throw 'Exclusive evidence creation did not preserve the existing entry.'
        }
        $Source = Join-Path $Sandbox 'source.bin'
        [IO.File]::WriteAllBytes($Source,$Original)
        $Captured = Read-Evidence $Source 1024
        $Captured.handle.Dispose()
        [IO.File]::WriteAllBytes($Source,[Text.Encoding]::UTF8.GetBytes('changed later'))
        if ($Captured.sha256 -cne (Get-BytesDigest $Captured.bytes)) { throw 'Hash does not describe consumed bytes.' }
        $Rejected = $false
        try { Assert-EvidenceUnchanged $Source $Captured.sha256 } catch { $Rejected = $true }
        if (-not $Rejected) { throw 'Changed source was accepted.' }
        return 3
    } finally {
        $Resolved = [IO.Path]::GetFullPath($Sandbox)
        if (-not $Resolved.StartsWith($Root + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Test cleanup outside owned root.'
        }
        if ((Get-Item -LiteralPath $Resolved -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Linked test sandbox; preserve.'
        }
        $Entries = @(Get-ChildItem -LiteralPath $Resolved -Force)
        if (@($Entries | Where-Object {$_.Name -notin @('once.bin','source.bin') -or $_.PSIsContainer -or
            ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)}).Count) { throw 'Unexpected test contents; preserve.' }
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}

function Test-DocumentOnlyFailure($Receipt, [string]$Log, [string]$Digest, [int]$ExpectedCount) {
    # Input: receipt object/log/source digest strings. Output: bool; admit only the registered document failure.
    if ($null -eq $Receipt -or ($Receipt.returncode -isnot [int] -and $Receipt.returncode -isnot [long]) -or
        $Receipt.returncode -ne 1 -or $Receipt.unchanged -isnot [bool] -or -not $Receipt.unchanged -or
        $Digest -notmatch '^[0-9a-f]{64}$' -or $Receipt.before -cne $Digest -or $Receipt.after -cne $Digest) { return $false }
    $Failures = [regex]::Matches($Log,'(?m)^(FAIL|ERROR): (.+)\r?$')
    $Counts = [regex]::Matches($Log,'(?m)^Ran (\d+) tests in [0-9.]+s\r?$')
    $Summaries = [regex]::Matches($Log,'(?m)^FAILED \([^\r\n]+\)\r?$')
    return ($ExpectedCount -gt 0 -and $Counts.Count -eq 1 -and
        [int]$Counts[0].Groups[1].Value -eq $ExpectedCount -and $Failures.Count -eq 1 -and
        $Failures[0].Groups[1].Value -ceq 'FAIL' -and $Failures[0].Groups[2].Value.Trim() -ceq $RegisteredFailure -and
        $Summaries.Count -eq 1 -and $Summaries[0].Value.Trim() -match '^FAILED \(failures=1(?:, skipped=\d+)?\)$')
}

function Invoke-ProofSelfTests {
    # Input: none. Output: passed case count int; reject code errors, changed source and misleading summaries.
    $Digest = 'a' * 64
    $Valid = @{before=$Digest;after=$Digest;returncode=1;unchanged=$true}
    $Log = 'FAIL: ' + $RegisteredFailure + [Environment]::NewLine + 'Ran 100 tests in 0.1s' +
        [Environment]::NewLine + 'FAILED (failures=1, skipped=9)'
    $Changed = $Valid.Clone(); $Changed.before = 'b' * 64
    $Unstable = $Valid.Clone(); $Unstable.unchanged = $false
    $Passed = $Valid.Clone(); $Passed.returncode = 0
    $StringFlag = $Valid.Clone(); $StringFlag.unchanged = 'True'
    $Code = 'FAIL: test_code_bug (tests.test_runtime.Runtime.test_code_bug)' + [Environment]::NewLine + 'FAILED (failures=1)'
    $Cases = @(
        @{name='document-only';receipt=$Valid;log=$Log;expected=$true},
        @{name='code-failure';receipt=$Valid;log=$Code;expected=$false},
        @{name='changed-source';receipt=$Changed;log=$Log;expected=$false},
        @{name='unstable-source';receipt=$Unstable;log=$Log;expected=$false},
        @{name='already-passed';receipt=$Passed;log=$Log;expected=$false},
        @{name='string-flag';receipt=$StringFlag;log=$Log;expected=$false},
        @{name='additional-failure';receipt=$Valid;log=($Log+[Environment]::NewLine+$Code);expected=$false},
        @{name='error-not-failure';receipt=$Valid;log=$Log.Replace('FAIL: ','ERROR: ');expected=$false},
        @{name='wrong-summary';receipt=$Valid;log=$Log.Replace('failures=1, skipped=9','errors=1');expected=$false},
        @{name='not-full-suite';receipt=$Valid;log=$Log.Replace('Ran 100 tests','Ran 24 tests');expected=$false},
        @{name='missing-count';receipt=$Valid;log=$Log.Replace('Ran 100 tests','not a summary');expected=$false}
    )
    foreach ($Case in $Cases) {
        if ((Test-DocumentOnlyFailure $Case.receipt $Case.log $Digest 100) -ne $Case.expected) {
            throw ('Document-proof self-test failed: ' + $Case.name)
        }
    }
    return $Cases.Count
}

function Invoke-OfflinePython([string]$Product, [string]$Python, [string[]]$Arguments) {
    # Input: local executable/project and argument list. Output: exit/stdout/stderr object; filtered env, bounded owned process.
    $Info = [Diagnostics.ProcessStartInfo]::new($Python)
    $Info.WorkingDirectory = $Product
    $Info.UseShellExecute = $false; $Info.CreateNoWindow = $true
    $Info.RedirectStandardOutput = $true; $Info.RedirectStandardError = $true
    foreach ($Arg in $Arguments) { $Info.ArgumentList.Add($Arg) }
    $Info.Environment.Clear()
    foreach ($Name in @('SystemRoot','windir','PATH','TEMP','TMP','USERPROFILE','HOME','APPDATA','LOCALAPPDATA',
        'COMSPEC','PATHEXT','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA')) {
        $Value = [Environment]::GetEnvironmentVariable($Name,'Process')
        if ($null -ne $Value) { $Info.Environment[$Name] = $Value }
    }
    $Info.Environment['SystemRoot'] = [Environment]::GetFolderPath('Windows')
    $Info.Environment['windir'] = $Info.Environment['SystemRoot']
    $Info.Environment['PYTHONUTF8'] = '1'; $Info.Environment['PYTHONDONTWRITEBYTECODE'] = '1'
    $Process = [Diagnostics.Process]::Start($Info)
    $Stdout = $Process.StandardOutput.ReadToEndAsync(); $Stderr = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit(120000)) { $Process.Kill($true); throw 'Offline recheck timed out.' }
    return @{exit_code=$Process.ExitCode;stdout=$Stdout.GetAwaiter().GetResult();stderr=$Stderr.GetAwaiter().GetResult()}
}

function Get-SourceInfo([string]$Product, [string]$Python) {
    # Input: project/Python paths str. Output: source SHA and discovered test count, without executing tests.
    $Code = 'import json,unittest; from pathlib import Path; from wqb.maintenance_resolution import _code_digest; p=Path.cwd(); before=_code_digest(p); loader=unittest.TestLoader(); suite=loader.discover("tests",top_level_dir="."); assert not loader.errors; count=suite.countTestCases(); after=_code_digest(p); assert before==after; print(json.dumps(dict(digest=after,test_count=count)))'
    $Call = Invoke-OfflinePython $Product $Python @('-B','-c',$Code)
    if ($Call.exit_code -ne 0) { throw 'Source discovery failed.' }
    $Info = $Call.stdout | ConvertFrom-Json
    if ($Info.digest -notmatch '^[0-9a-f]{64}$' -or $Info.test_count -le 0) { throw 'Invalid source identity.' }
    return $Info
}

$SelfTests = (Invoke-ProofSelfTests) + (Invoke-EvidenceSelfTests)
if ($SelfTest) { @{self_tests=$SelfTests;status='PASS'} | ConvertTo-Json -Compress; return }
if (-not $PythonExe -or $BaseStem -notmatch '^[a-z0-9-]+$' -or $ResultStem -notmatch '^[a-z0-9-]+$') {
    throw 'Explicit Python and bounded evidence names required.'
}
$Product = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Workspace = [IO.Path]::GetFullPath((Join-Path $Product '../..'))
$Evidence = Join-Path $Product 'output/desktop-validation'
$Ancestor = Get-Item -LiteralPath $Evidence
while ($null -ne $Ancestor) {
    if ($Ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked evidence directory.' }
    $Ancestor = $Ancestor.Parent
}
$BasePath = Join-Path $Evidence ($BaseStem + '.json')
$BaseLog = Join-Path $Evidence ($BaseStem + '.log')
$ResultPath = Join-Path $Evidence ($ResultStem + '.json')
$DocLog = Join-Path $Evidence ($ResultStem + '-documents.log')
if ((Test-Path -LiteralPath $ResultPath) -or (Test-Path -LiteralPath $DocLog)) { throw 'Preserve prior evidence.' }
$Held = @()
try {
$VerifierBefore = (Get-FileHash -LiteralPath $PSCommandPath).Hash.ToLowerInvariant()
$ReceiptEvidence = Read-Evidence $BasePath $MaximumReceiptBytes
$Held += $ReceiptEvidence.handle
$LogEvidence = Read-Evidence $BaseLog $MaximumLogBytes
$Held += $LogEvidence.handle
$Decoder = [Text.UTF8Encoding]::new($false,$true)
$Receipt = $Decoder.GetString($ReceiptEvidence.bytes).TrimStart([char]0xfeff) | ConvertFrom-Json -AsHashtable
$Log = $Decoder.GetString($LogEvidence.bytes).TrimStart([char]0xfeff)
$Source = Get-SourceInfo $Product $PythonExe
$Before = $Source.digest
if (-not (Test-DocumentOnlyFailure $Receipt $Log $Before $Source.test_count)) { throw 'Not a source-unchanged document-only failure.' }
$DocBefore = @{}
foreach ($Name in @('AGENTS.md','todo.md','milestone.md')) {
    $DocBefore[$Name] = (Get-FileHash -LiteralPath (Join-Path $Workspace $Name) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$Call = Invoke-OfflinePython $Product $PythonExe @('-B','-m','unittest','tests.test_project_architecture','tests.test_project_entry_docs','-q')
$Output = $Call.stdout + $Call.stderr
$DocBytes = [Text.UTF8Encoding]::new($false).GetBytes($Output)
Write-EvidenceExclusive $DocLog $DocBytes
$DocEvidence = Read-Evidence $DocLog $MaximumLogBytes
$Held += $DocEvidence.handle
if ($DocEvidence.sha256 -cne (Get-BytesDigest $DocBytes)) { throw 'Generated document log changed.' }
if ($Call.exit_code -ne 0 -or $Output -notmatch '(?m)^OK\r?$') { throw 'Document recheck did not pass.' }
$AfterSource = Get-SourceInfo $Product $PythonExe
$After = $AfterSource.digest
if ($After -cne $Before -or $AfterSource.test_count -ne $Source.test_count) { throw 'Source changed during document recheck.' }
foreach ($Name in $DocBefore.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $Workspace $Name) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $DocBefore[$Name]) {
        throw 'Documents changed during recheck.'
    }
}
Assert-EvidenceUnchanged $BasePath $ReceiptEvidence.sha256
Assert-EvidenceUnchanged $BaseLog $LogEvidence.sha256
Assert-EvidenceUnchanged $DocLog $DocEvidence.sha256
if ((Get-FileHash -LiteralPath $PSCommandPath).Hash.ToLowerInvariant() -cne $VerifierBefore) { throw 'Verifier changed during recheck.' }
$Result = @{kind='offline_code_plus_document_recheck_v1';before=$Before;after=$After;unchanged=$true;returncode=0;
    base_suite_returncode=$Receipt.returncode;base_suite_rerun=$false;failed_code_tests_waived=$false;
    registered_failure=$RegisteredFailure;source_test_count=$Source.test_count;self_tests=$SelfTests;
    document_recheck_returncode=0;document_hashes=$DocBefore;
    base_receipt=@{path=$BasePath;sha256=$ReceiptEvidence.sha256};
    base_log=@{path=$BaseLog;sha256=$LogEvidence.sha256};
    document_log=@{path=$DocLog;sha256=$DocEvidence.sha256};
    verifier_sha256=$VerifierBefore}
Write-EvidenceExclusive $ResultPath ([Text.UTF8Encoding]::new($false).GetBytes(($Result | ConvertTo-Json -Depth 6)))
@{status='accepted_composite';proof=$ResultPath;source_digest=$After;full_suite_rerun=$false} | ConvertTo-Json -Compress
} finally { foreach ($Handle in $Held) { $Handle.Dispose() } }
