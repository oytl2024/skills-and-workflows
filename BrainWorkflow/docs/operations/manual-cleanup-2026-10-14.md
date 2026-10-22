# 手动清理清单

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
