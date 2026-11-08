# 手动清理清单

## 2026-11-06 Native Installation Replacement Audit

Pending verified Git sync and full-suite acceptance: replace only
`BrainWorkflow/output/desktop-application/installed/BrainWorkflow/` with the
verified build `20261106-113104-7809/dist space 中文/BrainWorkflow/`, then refresh
the adjacent three-key `installation.json` receipt. Both application trees have
356 files with identical relative names, zero reparse entries; installed root
has 357 files including its receipt (45,582,258 bytes at audit). Replacement
build is 45,592,870 bytes. Recheck containment, ancestors, file names and owned
processes immediately before publishing; no recursive removal is needed for
this identical-layout overwrite. Stage the receipt last so partial copy cannot
qualify as current. The old package remains reconstructible in local verified
build `20261105-193909-3140`; product code is Git recoverable after sync.

This is a generated application deployment, not permission to remove historical
verification packages, source material, research/recovery records, private config,
credentials or browser profiles. WebView2 profiles under `runs/desktop` are not
inside the replacement tree. The three distinct old semantic inventories remain
protected; no real inventory retirement/deletion is implied. Outcome and loaded
revision must be recorded after execution, never inferred from this audit.

Executed after verified Git equality at
`29240b6c6f5a9a0fcdeec6a86743d6d5aec0c95b`: 356 application files overwritten
at the audited identical relative paths, each copied hash checked; no recursive
deletion, private configuration, profile or research evidence touched. Receipt
published last with source revision
`9944984c350f1485579f8862c9bdde867739b4da9aed2882b634f228d3aeee98`
and EXE SHA256
`ffa435a58671e296c2b4d2d051498892f67fda5f2196ad8a1f3bd24a2d36ea34`.
The outer `BrainWorkflow.vbs` opened the installed native window. Real-loopback
health and application snapshot verified source/assets, outer workspace, external
configuration and canonical knowledge/runs roots. Top-level mission-state hashes
were unchanged; no Start command, capture, simulation or Alpha submission was
issued. The actual window and realtime overview were inspected. Private receipt:
`output/desktop-validation/installed-console-loaded-20261106.json`.
Post-install verification: 74 desktop/application/root-entry/normalization tests
passed in 11.805 seconds. Production/test sources remain the full-suite snapshot;
only this deployment audit is changed for the cleanup-outcome commit.

## 2026-10-21 单一根入口

用户明确批准仅在 brain 最外层保留 AGENTS.md、todo.md、milestone.md。仓库 AGENTS 的独有规则已合入根 AGENTS；下列四个普通文件允许删除，原版本可从已同步的 `7bff56b` Git 历史恢复：`skills-and-workflows/AGENTS.md`、`skills-and-workflows/todo.md`、`skills-and-workflows/milestone.md`、`skills-and-workflows/BrainWorkflow/todo.md`。后三者只是根文件跳转页，无独有任务正文；历史归档不删除。入口回归改为检查根规则完整、嵌套入口不存在、归档哈希不变。本文旧段落中的“仓库 AGENTS.md”指当时位置，当前规则唯一入口为 brain/AGENTS.md。

根三文件处于共享仓库之外，本次不移动 Git 根目录，也不将私人任务日志上传；GitHub同步的是删除变更、引用说明和回归测试，不代表根三文件已被远端备份。仓库 README 明确说明需从外层工作区入口维护。

结果：四条路径经工作区边界、普通文件及祖先无链接核验后，已用原生 LiteralPath 非递归删除；规则有效内容合并至根 AGENTS.md，历史归档未改。先验证新断言失败，再完成合并并通过 24 项架构/入口回归（0.079 秒）；保留原有 25000 字符入口限额。源码、脚本和看板的架构入口已使用工作区根，无须修改运行代码。

## 2026-10-21 全工作区依赖复核（第二轮）

用户批准整个 brain 的无用文件审计。删除前同步基线：`3e7c6847497147558c726584b7cc3688402fb388`，本地与 origin/agent/brainworkflow-phase2 一致。以下均为未跟踪的可再生缓存或空测试目录，不需要上传私有内容备份。

本轮删除白名单，相对 `skills-and-workflows/BrainWorkflow/`：

- `output/__pycache__/`：1 个 pyc，仅当对应 Python 源码存在时删除。
- `scripts/__pycache__/`：7 个 pyc，同上。
- `tests/__pycache__/`：134 个 pyc，同上。
- `wqb/__pycache__/`：115 个 pyc，同上。
- `tests/_tmp_cli_0b4b262437a040168187e55b8524bad2/`
- `tests/_tmp_cli_22e382bebd704029b7ae7f3eb7ac6af4/`
- `tests/_tmp_cli_3c2128dad0d84b4ca106ee68dc927ffd/`
- `tests/_tmp_cli_4b079cc354494f6b87a8279e8e0d4bb5/`
- `tests/_tmp_cli_4bee650eb9c14d168fb45c5a2c2c3acb/`
- `tests/_tmp_cli_4dc9d98d0e0e4a3d9523a1ef8a5c5f76/`
- `tests/_tmp_cli_62318a53da454e32b503f9a260dfdf43/`
- `tests/_tmp_cli_65da0ab9b5094e5b8fa6e0ee913b7003/`
- `tests/_tmp_cli_c5d363bb87d04ef79dc26d989c234a34/`

九个 `_tmp_cli_` 目录已核验为空，生成来源为 `tests/test_cli.py::make_run_dir/cleanup_run_dir`，不是研究运行。缓存仅逐文件删除 `.pyc`，拒绝子目录、链接、没有源文件的缓存及意外条目；最后只移除空目录，不递归扫除。

依赖检查结论：docs/knowledge 的示例账本仍被 knowledge_bootstrap/knowledge_vault_migration 使用；operator_data_semantics.md 是 operator_semantics 的默认来源；cache 是 CLI 默认目录并被历史来源引用。因此不删除这些文件。output 下 source-audit/source-preparation、浏览器验证与 sandbox-probe、维护日志是独有验证/来源证据或含浏览器资料，不因“不被 import”认定无用。根 knowledge/raw/machine/wiki、runs、archive、.superpowers、tools/signboard、management、规则/交接和历史兼容代码保留。敏感 profile/netstat 不在本轮权限内。

执行及回归结果：逐文件核验对应源文件存在后，原生非递归删除 257 个 pyc 和 13 个空目录（4 个缓存目录、9 个测试目录）。架构、入口、假设演示、CLI、知识库初始化及算符语义共 219 项离线测试通过（13.394 秒）；使用 `-B` 和 `PYTHONDONTWRITEBYTECODE=1` 防止回归重建缓存。回归后核验缓存与测试临时目录不存在，未修改运行代码或删除独有证据。进一步删除源码/历史材料需要证明替代关系与兼容性，不能仅靠静态零引用推断。

## 2026-10-21 版本同步与清理复核

本节是当前规则；下文 2026-10-14 的禁止提交/推送仅描述当时授权，不覆盖本次明确授权。新版本 `e975850` 已推送到 `origin/agent/brainworkflow-phase2`，本地与远端完整提交号一致；不强推、不修改默认分支、不删除 Git 历史。

本次普通清理白名单（基准目录仍为本文下述 brain 根目录）：

- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/coverage.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/design.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/diagnostics.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/drafts.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/experiment.json`

这五份是虚构离线演示生成物，不是真实策略或回测记录；当前源码、测试、规则、知识来源索引未引用这些具体文件。生成器 `scripts/demo_hypothesis_design.py` 已在远端版本保存，保留生成器与测试，仅清理输出。只删除列出的普通文件；若目录出现新增内容、链接或路径越界，停止，不整目录递归清空。

本轮执行状态：首次 PowerShell 删除在创建进程前被策略拒绝，未换工具绕过。2026-10-21 用户切换为 workspace-write 并重新批准开始删除后，核验本地与远端跟踪提交均为 `7dff0435ef09cf37f95012e2facfc13e21e6feb7`；重新核验五条绝对路径、工作区边界、祖先无链接且目录恰有五份文件后，以 PowerShell `Remove-Item -LiteralPath` 非递归删除五份文件及空父目录，确认目录不存在。未删除其他输出或受保护资料；这些生成物本身不在 Git 中，远端保存的是可重建它们的生成器，而非输出备份。

另外，将用户早已批准且已经物理删除的两个无关技能目录 `skills/chaptered-course-lecture-builder/`、`skills/glimpse/` 的十条删除变更提交并推送；原文件仍可从前一远端提交恢复，不重建这些目录。

明确保留：实际 `knowledge/`、根及产品 `runs/`、原始资料、当前语义 release/历史任务及来源回执、维护证明、`.superpowers/sdd/`、已被文档引用的 source-audit/source-preparation、当前看板依赖、配置和兼容代码。`configs/stage1_usa_d1.yaml` 仍是 CLI 默认且被测试使用，不按旧名称删除。

需要另行具名批准的敏感候选：产品 `.desktop-launch-smoke-20260923/` 内的旧浏览器 profile，以及根 `netstat_ports.txt` 网络诊断。本轮不删除、不读取 Cookie/token 内容、不上传这些资料。

`archive/stage1_legacy_20260712/` 混有旧源码、原始研究、文档、配置和历史运行；其旧源码不全处于共享 Git 的历史中。没有逐文件证明完成吸收、备份及无敏感内容之前，不把整个 archive 认作可删旧版本，也不为了备份将其私有内容上传 GitHub。截图、真实日志和维护审查报告不按日期批量删除。

删除后验证：39 项架构、入口文档及假设演示测试通过（1.714 秒），演示目录未被重新生成，`git diff --check` 通过。首次沙箱测试受临时目录写权限阻止，经正式审批在沙箱外重跑通过；未修改权限配置或产品代码。

执行结果与最新待办统一记录在根 `todo.md`。以后每次版本更新均按仓库 `AGENTS.md` 的 `BrainWorkflow Version Sync And Cleanup` 执行，而非按旧日期的清单重复删除。

核验日期：2026-10-14。基准目录：`C:\Users\oytl\Desktop\pyproject\brain`。

本清单用于人工资源管理器操作，不是自动删除脚本。永久删除不会进入回收站；只选下面列明的路径，不要按相似名称批量删除。删除前若出现新增内容、程序占用或敏感文件，停止并重新核验。执行环境拒绝了代理删除命令，本文件不代表删除已完成。

完成记录：用户已报告按 A 删除；维护窗口在 2026-10-14 只读核验 A 的14条路径全部不存在，相关 Git 删除变更保留。C 部分未批准删除的内容仍受保护。

## A. 可以手动删除

以下测试目录已核验为仅有空目录结构；历史入口已检查当前 wqb/tests/configs/management/scripts/操作文档/README 静态引用，没有发现调用它们的引用。删除的是旧入口，不删除对应 CLI 能力或配置。

```text
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\.exe
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\.test-fixed-probe
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\.test-tmp
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\tmp5mica4jd
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\run_stage1.ps1
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\run_stage1.sh
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\template.json
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\scripts\resume_news7_scout.ps1
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\scripts\resume_news7_scout.sh
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\scripts\resume_ypp_30_repair.ps1
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\scripts\run_fundamental3_semantic_scout.ps1
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\scripts\run_fundamental3_semantic_scout.sh
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\scripts\stage1_live_resume.ps1
C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow\scripts\stage1_loop.sh
```

旧运行脚本绑定的是 2026 年 7 月的一次性任务、字段或 Alpha；部分还设置旧代理7890和网络重试参数，不是当前 Console 自动运行入口。配置 `configs/stage1_usa_d1.yaml` 暂时保留，其他代码仍可能使用它。`template.json` 是未被当前代码调用的旧公式示例，不是 machine/template_library。

## B. 已经不存在，无需再删

2026-10-14 再次核验，下列路径不存在；不存在仅证明当前磁盘状态，不表示代理执行过删除。

```text
skills-and-workflows\skills
%SystemDrive%
skills-and-workflows\BrainWorkflow\%SystemDrive%
skills-and-workflows\BrainWorkflow\MagicMock
skills-and-workflows\BrainWorkflow\HELLO
skills-and-workflows\BrainWorkflow\NVIDIA Corporation
```

百分号路径是曾经在工作区错误生成的字面目录名，不是 Windows 系统盘变量；不要在地址栏输入它。

## C. 现在先不要删

| 路径 | 原因及后续处理 |
| --- | --- |
| `.git/`、LICENSE、`.gitignore`、README | 仓库历史和正常工程元数据；不是杂物 |
| 根 `AGENTS.md`、`todo.md`、`milestone.md` 和仓库兼容入口 | 权威规则/交接及已有测试契约；入口文件指向根文档，不是重复账本 |
| 根 `knowledge/`、`runs/` | 活动任务、资料来源、身份及维护证明；必须保留 |
| `tools/signboard/`、产品 `management/` | 当前看板依赖和集成 |
| 产品 `configs/`、两级 CMD/VBS 启动入口 | 当前 CLI/桌面依赖；不要按“入口重复”盲删 |
| 产品 `runs/` | 混有历史 live/source 运行及测试残留；先做逐身份来源和活动引用审计，再单独形成迁移/删除清单 |
| 产品 `output/` | 验收和诊断证据，不等于无关目录；可后续制定保留规则 |
| `archive/`、产品 `docs/knowledge/` | 历史平台资料及判断可能尚未完全进入新语义库；本次知识补全应先利用、检查引用，不能一刀切 |
| 仓库 `.superpowers/` | 旧审查报告/任务交接，不是安装的插件；可能有唯一工程证据，先确认需要保留的内容已被吸收 |
| 产品 `.desktop-launch-smoke-20260923/` | 历史测试浏览器 profile，含 Cookie/会话/token 文件；属于敏感删除，需单独明确批准 |
| 根 `netstat_ports.txt` | 旧网络诊断，非运行必需但可能含连接/进程信息；单独确认后删除 |

## 删除后核验

告知维护窗口“按 A 删好了”。维护窗口只读确认 A 路径不存在，核对 Git 删除变更属于这份白名单，运行现有入口/架构检查。不自动 commit/push，不修改真实运行，不通过重新生成残留伪造清理完成。

这只是本轮确定可删的清单，不宣称所有历史内容已经消化。未来测试使用可清理的独立临时目录；代码、脚本、文档和生成物分别放回既有目录，禁止新增无关根目录。

## 2026-10-22 Daily Budget Release Audit

- Before cleanup, local HEAD and GitHub branch `agent/brainworkflow-phase2` both equalled `f2000102802f4a3fb472b9b454382c2d9d72d05e`; push succeeded without force.
- Deletion set: empty. The24 changed product files are current source, regression tests, specification/plan and operator/maintainer documentation. The single new budget owner is imported by runtime, Start, planning, driver and audit consumers; tests cover retained legacy readers. No obsolete standalone implementation was introduced.
- Protected exact boundaries: outer `AGENTS.md`, `todo.md`, `milestone.md`, `knowledge/`, `runs/`, `archive/`, browser/credential/configuration material, Git history, current launchers and Signboard dependencies. Existing product `output/` and `tests/full-suite-maintenance.log` remain untouched by deletion. New full-suite logs and copied source-change failure receipts remain verification evidence; names/dates alone do not authorize removal.
- No recursive deletion, sensitive-file deletion, unrelated project cleanup, live research, WQB call, budget renewal or Alpha submission was performed by this audit. Daily policy activation was separately authorized and is recorded under the owning run, not inferred from cleanup.
- Follow-up verification and loaded-app evidence belong to root todo.md. Record this no-deletion audit in Git after the verified source push; do not manufacture obsolete files merely to produce a cleanup commit.

## 2026-10-23 Preplanned Desktop Integration Audit

- Verified source sync: local and remote `agent/brainworkflow-phase2` both
  `e05d2e2af8a6ea160776d6fb8d948312de26aeea`; push succeeded without force.
- Deletion set: empty. New `wqb` modules are imported by Start, runtime, Console
  or the packaged entry; legacy readers remain necessary for old runs. The
  frontend and build scripts are current dependencies, not duplicate products.
- Protected exact boundaries: outer `AGENTS.md`, `todo.md`, `milestone.md`,
  `knowledge/`, `runs/`, `archive/`, current launchers, credentials/configuration,
  profiles, Signboard dependencies, Git history and unrelated `output/` plus
  `tests/full-suite-maintenance.log`. No sensitive/private evidence was staged.
- `output/desktop-application/20261023-095722-9119`,
  `20261023-105748-7249` and `20261023-110338-1094` remain referenced by local
  build/native-smoke reports. They are verification evidence, not audited
  disposable candidates. `frontend/dist` and local build dependencies remain
  necessary for reproducible packaging; generated outputs are excluded from Git.
- Stable offline suite:2569 tests,3 skips,373.910s; frontend15 tests/typecheck/build
  pass. Final native fixture verifies source81b029b1662c734f3294fb9f403f359fe52950c1d8769ce9cc57d6d23cb73ee5.
  This audit does not grant deployment, old-proof renewal, research resume,
  platform/model calls, quota changes or Alpha submission.

## 2026-10-30 Semantic Maintenance Slice Audit

- Verified GitHub sync before audit: local and remote branch
  `agent/brainworkflow-phase2` both equal
  `e4759b21b1a785e380e0f83adc2290107bf5dcd7`; push was non-forced.
- Deletion set: empty. The new full-semantic modules serve preparation,
  authenticated execution, strict transport and read-only reporting through the
  existing knowledge-maintenance interfaces. They do not replace old-run readers
  or introduce a second runtime state machine. No files became disposable merely
  because these opt-in helpers were added.
- Preserve outer entry documents, `knowledge/`, `runs/`, `archive/`, current
  launchers, Git history, credentials/configuration/profiles and Signboard.
  Preserve existing product `output/` and `tests/full-suite-maintenance.log`.
  The private prepared inventory and coverage reports are referenced diagnostic
  evidence, not approved deletion candidates; no private material was uploaded.
- Frozen offline proof:2722 tests,4 skips,442.158s; source before/after
  `c9dee0211909d75d6115cf7c38be0b0356bf89a3b9bb3ebfea380464330e1b0f`.
  Frontend15 tests/typecheck/build pass. A nonblocking bundler directive warning
  is retained, not represented as an error-free build log.
- K5 actual consumption, bulk bounded excerpts, raw metadata and real-resource
  readiness remain open. This is a verified maintenance slice, not complete
  workflow delivery, formal app deployment or old-run proof renewal. No model,
  WQB, research resume, budget change, Alpha submission or deletion occurred.

## 2026-11-03 Verified Integration Audit

- Before this audit, non-forced GitHub push and local/remote equality verified:
  `agent/brainworkflow-phase2` = `58e6cae7c86deb6eb8ed2fe1a243bee1ee1f6434`.
- Exact deletion set: empty. Updated/new files are required product modules,
  focused regressions, build confinement and operating documentation. The owned
  transport module serves the existing group driver; legacy readers remain
  required for old-run recovery. No unrelated replacement framework was added.
- Preserve outer `AGENTS.md`, `todo.md`, `milestone.md`, launchers, Git history,
  `knowledge/`, `runs/`, `archive/`, Signboard, credentials/configuration/profiles,
  and the pre-existing product `output/` and `tests/full-suite-maintenance.log`.
- Actual raw captures/excerpts, semantic job inputs/results, failed verification
  logs, native fixtures and staged packages remain referenced recovery evidence.
  Intermediate package snapshots are not assumed Git-recoverable merely because
  the final source is synced. No wildcard, link/junction traversal or deletion ran.
- Current frozen offline proof: 2,816 tests, zero failures/errors, four skips,
  687.819 seconds; source before/after
  `075c350ad133e77b32ec116fe4f0a2326cb25d0e7b27c44a24c35794b9824f0c`.
  React15/typecheck/build passed. Build `20261103-145837-8680` matches that source;
  three isolated native launches each passed16 checks. No private vault, runtime
  data or build artifacts were uploaded with the source commit.
- Actual-vault acceptance remains blocked by stale/incomplete sources and the
  absence of a new finite explanation allowance; a date-only historical user note
  remains unresolved. The offline deployment-readiness receipt is not formal
  entry/resource activation, old-proof renewal or research/Alpha authority.
- Affected knowledge/desktop/root-entry regressions after this no-deletion audit:
  95 tests passed in 15.500 seconds; source remains the frozen digest above.
  Commit/push the audit and reverify local/remote equality; final results belong
  in outer `todo.md`. No proof or quota is silently renewed by this audit.

## Nov 3 approved AI Repair retirement audit

- User explicitly approved retiring old research execution while preserving historical evidence. Old AI Repair is no longer a supported recovery mode; this overrides only the old-run execution compatibility promise.
- Exact deletion candidates, all relative to BrainWorkflow: `wqb/repair_planning.py`, `wqb/repair_brief.py`, `wqb/repair_output_contract.py`, `tests/test_ai_repair_acceptance.py`, `tests/test_repair_planning.py`, `tests/test_repair_brief.py`, `tests/test_repair_output_contract.py`.
- These are tracked source/tests, recoverable from pre-cleanup Git history. Shared limits and receipt verification move to `repair_policy.py`; simulation accounting, locks, Stop and unknown-POST recovery remain. Production imports and surviving tests must no longer depend on the deleted modules.
- Exclusions: all knowledge/raw/machine/wiki, runs and receipts, Alpha/check identities, source evidence, credentials, configuration, profiles, archives and unrelated output. No archive is deleted merely because it records the retired design.
- Pre-cleanup: synchronize this plan/audit and verify HEAD against its intended remote without force before deletion. Code edits in progress are not final acceptance. Then verify each candidate is an ordinary tracked file inside the product, not a link/junction, delete the exact audited paths, run affected and full offline regressions and commit/push the finished version. A failed push stops deletion.
- This cleanup grants no platform/model calls, research resume, proof renewal, budget change or Alpha submission. Deployment and real-vault readiness remain separately blocked.
- Discovered disposable bytecode: `wqb/__pycache__/repair_brief.cpython-312.pyc` and `wqb/__pycache__/repair_planning.cpython-312.pyc`. These are reproducible interpreter caches of the Git-backed deleted modules, not research/model evidence. Remove these two literal ordinary files after containment/link checks; preserve other caches and all staged historical packages.
- Nov4 execution: all seven audited source/test files and both named bytecode files are absent; production imports no longer reference the removed modules. Shared deterministic verification is in `repair_policy.py`; retirement discovery is shared across Orchestrator/Console and new group initialization excludes only identity-verified retired history. Startup proof compensation does not create notices for retired missions.
- Frozen full verification: 2,820 tests, zero failures/errors, five skips, 645.977 seconds. Source before/after `4651deb0e81f35998cb7e6f5e892059d95d2f73c8661afeda7a52b06b79f7870`; log `output/desktop-validation/retire-ai-repair-final-full-suite-20261104.log`. Earlier failed diagnostic logs remain; they are not acceptance evidence.
- Loaded-source acceptance: isolated real HTTP Console showed retired history with no Resume and no notification process; history bytes stayed identical. Real old-run classification was retired/can_resume=false/can_start=true, group exemption valid, selected evidence hashes unchanged. Browser SSE and desktop/mobile checks passed with zero live API calls; screenshots retained under `output/desktop-validation/retirement-20261104/`.
- Scope remains source maintenance only. No live research, knowledge capture/model explanation, final Alpha submit, proof renewal, budget activation or formal EXE entry switch occurred. Existing real knowledge/deployment blockers remain; this is not whole-project live readiness. Final Git sync is recorded in outer todo.md.

## Nov 4 metric-directed Repair cleanup audit

- Implementation `d941b59cb604121bad9556afde7c0d7ceb0b661c` was pushed to `agent/brainworkflow-phase2`; exact local/remote equality was verified before this audit. No branch switch, merge or force push occurred.
- Deletion target set is empty: no exclusive obsolete source adapter was introduced or retired by this feature. The public catalog, compiler, tests and operational documentation are current dependencies. A no-target audit is not permission for an age/name-based sweep.
- Retain `output/desktop-application/20261104-142807-5366`: current offline-tested package, not formal deployment. Retain superseded `output/desktop-application/20261104-141503-9289` as diagnostic source/build evidence from the first failed full-suite generation, not a selectable current version. It contains an intermediate working source snapshot not represented by an implementation commit.
- Retain `output/desktop-validation/metric-directed-repair-full-suite-20261104.log` (failed diagnostic), `metric-directed-repair-final-full-suite-20261104.log` (current acceptance), matching build logs and isolated desktop/mobile screenshots. Keep prior referenced output and the pre-existing untracked `tests/full-suite-maintenance.log`; do not upload potentially private diagnostics merely for backup.
- Exclude all root knowledge/raw/machine/wiki, runs/identities/checks/recovery evidence, credentials/config secrets, browser state, Git history and canonical root rules/architecture/handoff. No file in these boundaries was deleted, recaptured, refreshed or renewed.
- Final stable verification: 2,862 tests passed, five skips, 835.716 seconds; digest before/after `3eee974f07e8ec2c47e95f8ff9fda3ae91c5abaf51ca8469940f5166b1b72add`. Packaged backend revision `a7101e6feecc31fa9a8c27892507a3c7bfd6174f7e6f5825fcf1932735b17f19` matches source. Rerun affected entry/Console regressions after this documentation-only audit and synchronize the audit commit.
- Real local USA D1 TOP3000 resources remain 0 usable / 298 source diagnostics. Source/index/storage work is pending; this audit grants no gate waiver, platform/model calls, research resume, proof renewal, quota change, final Alpha submission or formal entry activation.
- Post-audit entry/Console regressions: 66 tests passed (one skip), 5.316 seconds; source/test/catalog digest is unchanged. No deletions were performed.

## Nov 5 source/lifecycle verified-slice audit

- Implementation `1944c80d386602a21a2c9edb96524d7ee40f8618` was pushed to
  `agent/brainworkflow-phase2` and exact local/remote equality verified before
  this audit. No force push, branch switch, implicit merge or real deletion.
- Stable source/test/catalog digest:
  `e87cd30998d4a734bf39d4f05805f38a1b7696dce9981f755c9660dd2d3d70fd`.
  Full suite: 2,943 tests, eight skips, 703.688 seconds. Log:
  `output/desktop-validation/source-lifecycle-verified-full-suite-20261104.log`.
  Package `output/desktop-application/20261104-234500-7080` and isolated browser
  loaded revision `858b3beed212af61e7bac802b7860ed58bdeb0bf655d38ba2ac266900772b9cc`
  match source; the formal entry was not activated.
- Actual deletion target set is empty. No source adapter was retired in this
  slice. The actual vault has no obsolete active-layout candidates. SQLite,
  current shared inventory and detailed coverage objects are current derived
  dependencies; new code/tests/docs are Git-backed current implementation.
- The following distinct, nonduplicate old inventories remain protected, not
  approved for deletion (paths relative to outer `knowledge/`):

| Path | Bytes | SHA256 |
| --- | ---: | --- |
| machine/semantic_jobs/0d4647b571b22371f8bacaec701965f916282ef534dfc1d9e2caad34609b9c97/inventory.jsonl | 696661460 | bf510eac0f34edb386ffefb3d6bd6c6e25f88563bf143d582b894a320b6b7aa9 |
| machine/semantic_jobs/23d66f9281475febb505dc1e36dfae9e40b81bcac5db264421ab305d931aaab3/inventory.jsonl | 696257228 | 889ab8cc6f26a5eb8358cced10b57a8726ca64e2635cdac6b83f4750c823beec |
| machine/semantic_jobs/92557c1ddb62f0bdee6ae730bda5a34d9c885eb0045fa4b9f91ed7ce97333d4a/inventory.jsonl | 692988905 | a528a299cdb77e1a55b07e66ad9019f59619b08ccb28c4aea57cf46a8922938b |

- Read-only audits validated each 88,670-target inventory and observed its
  prepared job directories. They do not establish job-content safety,
  authenticated supersession, external-reference closure or shared-writer
  serialization/recovery. `apply_semantic_retirement` deliberately refuses.
  Approximately 2.1 GB remains; P4 machine retirement is incomplete, not hidden
  behind a successful obsolete-layout cleanup or health check.
- Preserve intermediate packages `20261104-232445-7010` and
  `20261104-232849-2823`, interrupted/failed full-suite logs, browser timeout
  diagnostics and intermediate inventory generations as bound investigation
  evidence. Do not age-sweep them or upload private output merely for backup.
- Exclusions: all original raw, current machine resources/releases, wiki
  experience, research/run/check/POST/Stop/accounting/maintenance evidence,
  credentials/config secrets, browser state, Git history and outer entry docs.
  Capture age and the two unexplained source hashes were not renewed or waived.
- Formatting-only minor deferred to the next source-tested change: one extra
  final blank line in `tests/test_field_source_catalog.py`. The staged whitespace
  check reported it; it is not a test failure. Keeping the tested bytes avoids
  disguising a new digest as the existing full-suite proof.
- This is a verified implementation checkpoint, not whole-plan closure or
  authority for platform/model calls, research resume, proof renewal, budget
  changes, Alpha submission or formal deployment. Post-audit regression and
  documentation-only synchronization follow; outer todo.md owns their result.

## Nov5 approved Signboard retirement audit

- Subsequent user-authorized retry under explicit sandbox escalation succeeded.
  Git local/remote equality at `2da3830e4ccb9756e86ab4d81ba7866ca923446d`
  was rechecked; all exact targets below passed containment, ancestor/descendant
  reparse and directory file-count checks. Native Remove-Item removed management,
  tools/signboard and the six listed exclusive Python/script/test files, including
  the four named sensitive paths. No knowledge/research file was deleted. The
  first retry's parent-path parameter error occurred before any deletion; the
  corrected same-tool command succeeded. Earlier refusal is historical only.
- Post-delete verification: 30 Signboard-retirement/root-architecture/entry
  tests passed in 0.735 seconds. Runtime/frontend/scripts/test references are
  confined to the deliberate surviving retirement regression. Research Console,
  desktop and shared architecture parser remain. This does not certify pending
  P4 code or the entire application, and does not activate research/deployment.

- Execution outcome: deactivation/audit commit
  `2da3830e4ccb9756e86ab4d81ba7866ca923446d` was pushed and remote equality
  verified; 31 board/root regressions passed. The subsequent native literal-path
  deletion command was rejected by execution policy before process creation.
  No target was deleted. Do not bypass this rejection with another tool/language.

- User retired all Signboard functionality. Named additional approval covers
  `BrainWorkflow/management/.signboard-state`, `.signboard-smoke-fresh`,
  `.signboard-smoke-verified` and `signboard-window.png` exclusively. General
  browser state and research evidence are excluded.
- After verified Git synchronization, delete the workspace-contained product
  `management/` tree (144 files, 9207621 bytes at audit),
  `wqb/signboard_launcher.py`, `wqb/architecture_viewer.py`,
  `scripts/verify_architecture_browser.py`, `scripts/verify_architecture_live.py`,
  `tests/test_architecture_viewer.py`, `tests/test_signboard_launcher.py`, and
  outer `tools/signboard/` (79 files, 550820662 bytes). Recheck literal resolved
  paths, reparse points and unexpected contents immediately before deletion.
- Product sources and seven historical cards are recoverable from Git
  `23b70093a2a01c171aca9b81e3bfa7d3f7f55dcb`; cards contain no unique open task
  absent root todo/milestone. The tools tree is the reproducible 1.7.4 installer,
  SHA256SUMS and application. Approved profiles/screenshot are not Git-backed.
- Keep `project_architecture.py`, canonical root documents, Console/desktop,
  `test_signboard_retirement.py`, mixed architectural specifications and bound
  historical verification packages. Never sweep files merely mentioning board.
- No links found in either tree. Process-path audit found zero verified owned
  processes, but inaccessible process paths prevent a global absence claim.
  Do not terminate processes by name; locked files remain a visible blocker.
- Knowledge inventory retirement is separate and NOT complete: the read-only
  real-vault probe verified 88670 replacement identities in 11.515 seconds,
  but reference scanning failed closed at its 30-second limit. No real inventory
  has been archived, marked retired or deleted. Preserve all three old copies
  until reference closure and the approved transaction are verified.
- Post-audit regression: 146 tests passed, one skip, 6.671 seconds (root entry,
  source directory, guarded cleanup and Console contracts). No source/test
  edits or real deletions followed the stable full-suite proof.

## Nov8 Catalog Admission Desktop Audit

- Pending accepted update; no installation or deletion is authorized by this
  audit alone. Full offline proof and verified branch push must precede replacement.
- Exact generated distribution: `output/desktop-application/20261108-223912-0783/`
  with its `dist space` application tree. Destination remains
  `output/desktop-application/installed/BrainWorkflow/` inside the workspace.
- Read-only containment/link/layout audit: old 356 files, new 358; only additions
  are `_internal/wqb/measurement_window.py` and
  `_internal/wqb/research_resource_catalog.py`. No old-only paths; deletion list
  is empty. Generated installation receipt is replaced last after copied hashes
  match. Source changes remain Git-recoverable after verified synchronization.
- Keep all original knowledge, research identities/results/recovery evidence,
  profiles, private config and prior source-bound verification evidence. No
  browser/profile or distinct historical-inventory cleanup is part of this update.
- Isolated packaged smoke passed: native window, loaded code/context, WebView2,
  assets and snapshot. It used disposable roots, issued no Start or platform call,
  and stopped only its owned GUI/backend. This does not replace full regression.
