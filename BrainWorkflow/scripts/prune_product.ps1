param([switch]$Apply, [switch]$ApprovedProfiles, [switch]$DisposableOnly)
$ErrorActionPreference='Stop'
$Product=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Workspace=[IO.Path]::GetFullPath((Join-Path $Product '../..'))
$Runs=Join-Path $Workspace 'runs'
$Knowledge=Join-Path $Workspace 'knowledge'
$Audit=Join-Path $Runs 'product_cleanup_audit.json'
$Targets=[Collections.Generic.List[string]]::new()

function Assert-Local([string]$Path) {
    # Input: exact path. Output: normalized workspace path; reject traversal and linked ancestors.
    $Full=[IO.Path]::GetFullPath($Path)
    if (-not $Full.StartsWith($Workspace+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Outside workspace.' }
    $Item=Get-Item -LiteralPath $Full -Force -ErrorAction SilentlyContinue
    while ($null -ne $Item) {
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked target/ancestor: $Full" }
        $Item=$Item.Parent
    }
    return $Full
}

function Add-Target([string]$Path) {
    # Input: explicit existing path. Output: None; append a literal audited target.
    if (Test-Path -LiteralPath $Path) { $Targets.Add((Assert-Local $Path)) }
}

function Add-ChildrenExcept([string]$Root,[string[]]$Keep) {
    # Input: parent and allowed child names. Output: None; select actual direct children, never a wildcard deletion.
    if (-not (Test-Path -LiteralPath $Root)) { return }
    foreach ($Item in Get-ChildItem -LiteralPath (Assert-Local $Root) -Force) {
        if ($Item.Name -notin $Keep) { Add-Target $Item.FullName }
    }
}

function Get-Size([string]$Path) {
    # Input: checked path. Output: logical bytes; default recursion never follows links.
    $Item=Get-Item -LiteralPath $Path -Force
    if (-not $Item.PSIsContainer) { return [long]$Item.Length }
    return [long]((Get-ChildItem -LiteralPath $Path -Recurse -Force -File |
        Where-Object {-not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)} |
        Measure-Object -Property Length -Sum).Sum)
}

function Save-SafetyState {
    # Input: canonical runs. Output: None; preserve exact old hashes/pending POST facts before deleting any run.
    $Hashes=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $Pending=[Collections.Generic.List[object]]::new()
    $PendingPath=Join-Path $Runs 'pending_submission_summary.json'
    if (Test-Path -LiteralPath $PendingPath) {
        foreach ($Record in (Get-Content -LiteralPath $PendingPath -Raw | ConvertFrom-Json).records) {
            $Pending.Add($Record)
        }
    }
    $History=Join-Path $Runs 'simulation_identity_history.json'
    if (Test-Path -LiteralPath $History) {
        foreach ($Hash in (Get-Content -LiteralPath $History -Raw | ConvertFrom-Json).identities) { [void]$Hashes.Add($Hash) }
    }
    foreach ($Run in Get-ChildItem -LiteralPath $Runs -Directory -Force) {
        $Events=@()
        foreach ($Name in @('simulation_events.jsonl','all_alphas.jsonl')) {
            $Path=Join-Path $Run.FullName $Name
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { continue }
            foreach ($Line in [IO.File]::ReadLines($Path)) {
                if (-not $Line.Trim()) { continue }
                $Row=$Line | ConvertFrom-Json -AsHashtable
                if ($Row.expression_hash) { [void]$Hashes.Add([string]$Row.expression_hash) }
                if ($Name -eq 'simulation_events.jsonl') { $Events+=,$Row }
            }
        }
        $Closed=[Collections.Generic.HashSet[string]]::new()
        foreach ($Event in $Events) {
            if ($Event.event -in @('CHECKED','ERROR','SUBMISSION_REJECTED')) { [void]$Closed.Add([string]$Event.expression_hash) }
        }
        foreach ($Event in $Events) {
            if ($Event.event -in @('SUBMISSION_STARTED','SUBMITTED') -and
                -not $Closed.Contains([string]$Event.expression_hash)) {
                $Pending.Add(@{run_id=$Run.Name;expression_hash=$Event.expression_hash;event=$Event.event;
                    attempt_id=$Event.attempt_id;progress_url=$Event.progress_url;alpha_id=$Event.alpha_id})
            }
        }
    }
    $Values=@($Hashes | Sort-Object)
    $Serialized=ConvertTo-Json -InputObject $Values -Compress
    $Digest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($Serialized))).ToLowerInvariant()
    $Value=@{schema_version=1;identities=$Values;identities_sha256=$Digest}
    [IO.File]::WriteAllText($History,($Value|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $Runs 'pending_submission_summary.json'),
        (@{schema_version=1;history_only=$true;records=@($Pending)}|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
}

function Save-CompiledCaseSources {
    # Input: compiled wiki cases. Output: None; keep only cited local receipts, not whole run histories.
    $Cases=Join-Path $Knowledge 'wiki/60_research_cases'
    if (-not (Test-Path -LiteralPath $Cases)) { return }
    $Destination=Join-Path $Knowledge 'raw/research/compiled_case_sources'
    $Mappings=@{}
    foreach ($Case in Get-ChildItem -LiteralPath (Assert-Local $Cases) -File -Filter '*.md') {
        $Text=[IO.File]::ReadAllText($Case.FullName)
        foreach ($Match in [regex]::Matches($Text,'(?m); receipt ([^\r\n]+)')) {
            $Original=[Net.WebUtility]::HtmlDecode($Match.Groups[1].Value)
            if (-not [IO.Path]::IsPathFullyQualified($Original)) { continue }
            $Source=Assert-Local $Original
            if (-not $Source.StartsWith($Runs+'\',[StringComparison]::OrdinalIgnoreCase) -or
                [IO.Path]::GetExtension($Source) -ne '.json') { throw 'Unexpected case source.' }
            if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "Missing compiled case source: $Source" }
            New-Item -ItemType Directory -Path $Destination -Force | Out-Null
            $Hash=(Get-FileHash -LiteralPath $Source).Hash.ToLowerInvariant()
            $Target=Join-Path $Destination ($Hash+'.json')
            Copy-Item -LiteralPath $Source -Destination $Target -Force
            if ((Get-FileHash -LiteralPath $Target).Hash.ToLowerInvariant() -ne $Hash) { throw 'Case source copy differs.' }
            $Relative='raw/research/compiled_case_sources/'+$Hash+'.json'
            $Mappings[$Original]=$Relative
            $Text=$Text.Replace($Match.Groups[1].Value,$Relative)
        }
        [IO.File]::WriteAllText($Case.FullName,$Text,[Text.UTF8Encoding]::new($false))
    }
    if ($Mappings.Count) {
        [IO.File]::WriteAllText((Join-Path $Destination 'source_map.json'),
            ($Mappings|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
    }
}

Add-ChildrenExcept $Runs @('daily_simulation_budget','daily_simulation_budget.charge.guard',
    'daily_simulation_budget.init.guard','daily_simulation_budget.route.guard',
    'simulation_identity_history.json','pending_submission_summary.json','maintenance_channel.json','product_cleanup_audit.json')
Add-Target (Join-Path $Workspace 'archive')
Add-Target (Join-Path $Workspace 'netstat_ports.txt')
Add-Target (Join-Path $Product 'runs')
Add-Target (Join-Path $Product 'arguments.txt')
Add-Target (Join-Path $Product 'frontend/node_modules')
if (-not $DisposableOnly) {
    Add-ChildrenExcept (Join-Path $Product 'docs') @('operations')
    Add-ChildrenExcept (Join-Path $Product 'docs/operations') @('user_workflow_manual.md',
        'workflow-toolchain-map.md','ai-execution-boundary.md','runtime-renewal.md','product-storage.md')
}
$KeepOutput=@('desktop-application')
if ($DisposableOnly) { $KeepOutput+='desktop-build-deps' }
Add-ChildrenExcept (Join-Path $Product 'output') $KeepOutput
Add-ChildrenExcept (Join-Path $Product 'output/desktop-application') @('installed','.gitignore')
foreach ($Name in @('reports','semantic_inventories','semantic_jobs')) {
    Add-Target (Join-Path $Knowledge "machine/$Name")
}
Add-ChildrenExcept (Join-Path $Knowledge 'machine/field_catalogs') @('research-query.sqlite3','research-query.json','research-query.lock.guard')
Add-Target (Join-Path $Knowledge 'raw/maintenance')
foreach ($Base in @('wqb','tests','scripts')) {
    foreach ($Item in Get-ChildItem -LiteralPath (Join-Path $Product $Base) -Directory -Recurse -Force) {
        if ($Item.Name -eq '__pycache__') { Add-Target $Item.FullName }
    }
}

$Rows=@(foreach ($Target in $Targets) {
    @{path=[IO.Path]::GetRelativePath($Workspace,$Target);bytes=(Get-Size $Target)}
})
$Summary=@{schema_version=1;mode='dry_run';targets=$Rows;candidate_bytes=($Rows|Measure-Object bytes -Sum).Sum;
    excluded=@('knowledge raw/platform and community','current compiled resources/wiki',
        'Git/config/current app','minimal quota/dedup/unknown POST state','policy-rejected %SystemDrive% directories')}
if (-not $Apply) {
    [IO.File]::WriteAllText($Audit,($Summary|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
    @{mode='dry_run';targets=$Rows.Count;candidate_MB=[Math]::Round($Summary.candidate_bytes/1000000,2)}|ConvertTo-Json
    exit 0
}
if (-not $ApprovedProfiles) { throw 'Named profile approval is required before applying the audited cleanup.' }
$Head=(& git -C $Product rev-parse HEAD).Trim()
$Remote=& git -C $Product -c http.proxy=http://127.0.0.1:7897 ls-remote origin refs/heads/agent/brainworkflow-phase2
if ($LASTEXITCODE -ne 0 -or ($Remote -split '\s+')[0] -ne $Head) { throw 'Git synchronization required before deletion.' }
$Dirty=@(& git -C $Product status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or ($Dirty.Count -and -not $DisposableOnly)) { throw 'Commit intended source changes before deletion.' }
if ($DisposableOnly) {
    foreach ($Target in $Targets) {
        if ($Target.StartsWith($Product+'\',[StringComparison]::OrdinalIgnoreCase)) {
            $Relative=[IO.Path]::GetRelativePath($Product,$Target).Replace('\','/')
            $Tracked=@(& git -C $Product ls-files -- $Relative)
            if ($LASTEXITCODE -ne 0 -or $Tracked.Count) { throw "Tracked target deferred: $Relative" }
        }
    }
}
$Exe=Join-Path $Product 'output/desktop-application/installed/BrainWorkflow/BrainWorkflow.exe'
$Owned=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $Exe})
if (@($Owned|Where-Object {$_.CommandLine -match '--worker-module'}).Count) { throw 'Active worker; cleanup refused.' }
foreach ($Process in $Owned) {
    $Fresh=Get-CimInstance Win32_Process -Filter ('ProcessId='+$Process.ProcessId)
    if ($Fresh -and $Fresh.ExecutablePath -eq $Exe -and $Fresh.CreationDate -eq $Process.CreationDate) {
        Stop-Process -Id $Process.ProcessId
        Wait-Process -Id $Process.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
    }
}
Save-SafetyState
Save-CompiledCaseSources
$Budget=@{}
foreach ($Item in Get-ChildItem -LiteralPath (Join-Path $Runs 'daily_simulation_budget') -File -Recurse) {
    $Budget[$Item.FullName]=(Get-FileHash -LiteralPath $Item.FullName).Hash
}
$Removed=[long]0
$Summary.mode='applying'
$Summary.completed_paths=@()
$Summary.git_commit=$Head
$Summary.named_profile_approval=$true
[IO.File]::WriteAllText($Audit,($Summary|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
foreach ($Target in $Targets) {
    $Checked=Assert-Local $Target
    if (-not (Test-Path -LiteralPath $Checked)) { continue }
    $Links=@(Get-ChildItem -LiteralPath $Checked -Recurse -Force -ErrorAction Stop |
        Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint})
    if ($Links.Count) {
        $Modules=[IO.Path]::GetFullPath((Join-Path $Product 'frontend/node_modules'))
        $Validation=[IO.Path]::GetFullPath((Join-Path $Product 'output/desktop-validation'))
        foreach ($Link in $Links) {
            $ModuleLink=$Checked -eq $Modules -and $Link.FullName.StartsWith($Modules+'\',[StringComparison]::OrdinalIgnoreCase)
            $AuditedHomes=@('packaged-smoke-20261103-144423-33840','packaged-smoke-20261103-144715-27436',
                'packaged-smoke-20261103-150516-30476','packaged-smoke-20261103-150528-34120',
                'packaged-smoke-20261105-194028-22100')
            $KnownCache=$false
            foreach ($TestHome in $AuditedHomes) {
                $Expected=Join-Path $Validation "$TestHome/home/AppData/Local/Microsoft/Windows/INetCache/Content.IE5"
                if ($Checked -eq $Validation -and $Link.FullName -eq $Expected -and
                    $Link.LinkType -eq 'Junction' -and $Link.Target -eq (Join-Path $Link.Parent.FullName 'IE')) {
                    $KnownCache=$true
                }
            }
            if (-not $ModuleLink -and -not $KnownCache) { throw "Unaudited cache link: $($Link.FullName)" }
            Remove-Item -LiteralPath $Link.FullName -Force
        }
    }
    $Removed+=Get-Size $Checked
    Remove-Item -LiteralPath $Checked -Recurse -Force
    $Summary.completed_paths+=,[IO.Path]::GetRelativePath($Workspace,$Checked)
    $Summary.removed_bytes=$Removed
    [IO.File]::WriteAllText($Audit,($Summary|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
}
foreach ($Path in $Budget.Keys) {
    if ((Get-FileHash -LiteralPath $Path).Hash -ne $Budget[$Path]) { throw 'Quota ledger changed.' }
}
$SourceIndex=Join-Path $Knowledge 'machine/source_index.jsonl'
if (Test-Path -LiteralPath $SourceIndex) {
    $Remaining=@(foreach ($Line in [IO.File]::ReadLines($SourceIndex)) {
        if (-not $Line.Trim()) { continue }
        $Source=$Line | ConvertFrom-Json -AsHashtable
        if (-not ([string]$Source.path).StartsWith('raw/maintenance/')) { $Line }
    })
    [IO.File]::WriteAllLines($SourceIndex,$Remaining,[Text.UTF8Encoding]::new($false))
}
$Summary.mode='applied'
$Summary.removed_bytes=$Removed
$Summary.git_commit=$Head
$Summary.named_profile_approval=$true
[IO.File]::WriteAllText($Audit,($Summary|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
@{mode='applied';removed_MB=[Math]::Round($Removed/1000000,2);targets=$Rows.Count;quota_preserved=$true}|ConvertTo-Json
