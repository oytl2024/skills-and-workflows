# 手动清理清单

## 2026-10-21 版本同步与清理复核

本节是当前规则；下文 2026-10-14 的禁止提交/推送仅描述当时授权，不覆盖本次明确授权。新版本 `e975850` 已推送到 `origin/agent/brainworkflow-phase2`，本地与远端完整提交号一致；不强推、不修改默认分支、不删除 Git 历史。

本次普通清理白名单（基准目录仍为本文下述 brain 根目录）：

- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/coverage.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/design.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/diagnostics.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/drafts.json`
- `skills-and-workflows/BrainWorkflow/output/structured-template-m1-demo-fixture/experiment.json`

这五份是虚构离线演示生成物，不是真实策略或回测记录；当前源码、测试、规则、知识来源索引未引用这些具体文件。生成器 `scripts/demo_hypothesis_design.py` 已在远端版本保存，保留生成器与测试，仅清理输出。只删除列出的普通文件；若目录出现新增内容、链接或路径越界，停止，不整目录递归清空。

本轮执行状态：带绝对路径、边界和链接核验的 PowerShell 删除命令在创建进程前被执行策略拒绝，五份文件尚未删除。不得改用 Python、其他 shell 或其他接口绕过拒绝；本节提供的是待执行清单，不是清理完成证明。

另外，将用户早已批准且已经物理删除的两个无关技能目录 `skills/chaptered-course-lecture-builder/`、`skills/glimpse/` 的十条删除变更提交并推送；原文件仍可从前一远端提交恢复，不重建这些目录。

明确保留：实际 `knowledge/`、根及产品 `runs/`、原始资料、当前语义 release/历史任务及来源回执、维护证明、`.superpowers/sdd/`、已被文档引用的 source-audit/source-preparation、当前看板依赖、配置和兼容代码。`configs/stage1_usa_d1.yaml` 仍是 CLI 默认且被测试使用，不按旧名称删除。

需要另行具名批准的敏感候选：产品 `.desktop-launch-smoke-20260923/` 内的旧浏览器 profile，以及根 `netstat_ports.txt` 网络诊断。本轮不删除、不读取 Cookie/token 内容、不上传这些资料。

`archive/stage1_legacy_20260712/` 混有旧源码、原始研究、文档、配置和历史运行；其旧源码不全处于共享 Git 的历史中。没有逐文件证明完成吸收、备份及无敏感内容之前，不把整个 archive 认作可删旧版本，也不为了备份将其私有内容上传 GitHub。截图、真实日志和维护审查报告不按日期批量删除。

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
