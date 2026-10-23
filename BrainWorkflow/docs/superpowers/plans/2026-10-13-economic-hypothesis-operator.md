# Economic Hypothesis And Operator Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使独立知识维护能够编译条件算符用途与经济假设，并让研究真正使用不同机制、少量必要算符的可执行模板。

**Architecture:** 扩展现有账本与编译入口，以确定性契约校验模型建议；研究只消费 Start 时冻结的资源、假设和字段绑定。复用既有阶段、AI 只读执行器、模拟身份与恢复机制，不另建研究控制器。

**Tech Stack:** Python 3.12、现有 dataclass/JSON/JSONL/Markdown、unittest、现有 Codex CLI 只读适配器；不新增数据库、前端框架或第三方依赖。

**Spec:** `docs/superpowers/specs/2026-10-13-economic-hypothesis-operator-design.md`，用户已批准。

## Global Constraints

- 现有 `raw/machine/wiki` 顶层与单一知识库不变；machine 可含机器数据，人读经验留在 wiki。
- 每个触发点最多3个机制、每个机制最多2个条件分支；设为显式配置，默认3/2。
- 单个 Alpha 保持简单；沿用现有 Scout 复杂度限制，不擅自增加或放宽全局算符调用阈值。
- 批次最多30，服从剩余额度、显式轮数上限与原始权限；不凑数、不重复未知 POST。
- Repair 四句简报、检查顺序、资格证据、最终提交授权、Stop 和资源通知不得回归。
- 文本仅存可审核假设、理由、证据和决定，不索取模型隐含思维过程。
- 每个子代理显式 `reasoning_effort=medium` 或更低；不继承更高配置。
- 不读取凭据、不调用真实模型／WQB、不编译真实 vault、不恢复研究作为默认测试；真实知识维护另需用户启动或明确授权。
- 维护根 `todo.md`；架构落实后才更新 `milestone.md`，两者保持小于25000字符；历史内容无损归档。
- 保留所有既有脏文件；未获 commit/push 授权，任务中的提交检查点只记录交接，不执行 git commit。

## Review Focus

1. 重启或旧记录再次编译不能丢失新语义，不能让默认 seed 覆盖经验证内容；Task1/3负责。
2. 同名 VECTOR 字段、多个输入槽与显式多参数归约不能误绑定、重复归约或混用作用域；Task2负责。
3. 材料变化、恶意材料文本或无效模型输出不能获得事实等级、发布权限或预算；Task3负责。
4. 编译发布中断与并发 Start 不能读取混合机器资源版本，损坏清单不能静默退回旧缓存；Task4/6负责。
5. 无法组成多样批次、模型失败、Stop 与恢复不能重复调用模型、重复 POST 或静默停止；Task5/6/7负责。

## File Map And Shared Interfaces

以下路径均相对 BrainWorkflow；这是实施清单，不表示文件或能力已存在。

| 文件 | 职责 |
| --- | --- |
| 新 `wqb/semantic_contracts.py` | EvidenceRef、HypothesisCard、InputSlot、OperatorRole、SemanticPolicy 及结构／证据校验 |
| 修改 `operator_semantics.py`、`template_library.py` | 兼容扩展既有记录，保留新字段和旧版本语义 |
| 新 `wqb/template_binding.py` | 从冻结字段与算符记录绑定命名槽，输出固定内核和可审计绑定 |
| 新 `wqb/semantic_compilation.py` | 有界材料包、缓存、模型建议验证、增量语义编译协调 |
| 新 `wqb/semantic_publication.py` | 机器资源一致版本、暂存／发布／崩溃恢复与读取快照 |
| 新 `wqb/hypothesis_selection.py` | 约束内选择不同机制，合并等价方案，返回选择／拒绝理由 |
| 修改 `codex_ai_worker.py`、`ai_checkpoints.py` | 新任务严格输出契约与知识任务取消，不改变 Repair 协议 |
| 修改知识维护入口、Console job与状态、Start快照／计划／生成路径 | 实际接入，不只增加文档或 advisory 摘要 |

共享数据结构用 dataclass 或现有普通字典模式，不另造框架。所有新增函数入口注明输入、输出类型和职责。任务拥有接口；后续任务通过这些接口消费，不复制逻辑。

## Verification Environment

从 BrainWorkflow 执行。先在 PowerShell 设置 `SystemRoot=windir=C:\Windows`，使用 `C:\Users\oytl\AppData\Local\Programs\Python\Python312\python.exe`；下文 `python` 代表该解释器。否则 Windows 的 `_overlapped` 导入可能报10106，不能据此判断产品测试失败。

每项均先观察 RED，再实现 GREEN；测试只写临时 vault/run，不修改真实研究证据。每项最后更新 todo 中的变更、验证与精确下一命令；不提交整个脏工作区。

### Task 1: 兼容语义契约与假设卡

**Files:** 新 `wqb/semantic_contracts.py`、`tests/test_semantic_contracts.py`；修改 `wqb/operator_semantics.py`、`wqb/template_library.py` 及对应现有测试。

**Interfaces:**
- `evidence_ref_from_dict(row: dict) -> EvidenceRef`：source_path、sha256、capture_date、kind（documented/hypothesis/measured）、experiment_refs。
- `hypothesis_card_from_dict(row: dict) -> HypothesisCard`：data_meaning/mechanism/conditions/alternative/prediction/operator_roles/falsification 七项非空单句正文。
- `validate_semantic_record(row: dict, source_index: dict) -> list[dict]`：返回带 code/path/message 的问题，不自动提升证据等级。
- `SemanticPolicy` 默认 max_mechanisms=3、max_conditions_per_mechanism=2；无新增全局算符数阈值。

- [x] 1. 写失败测试：旧行解析与序列化兼容；新行往返保留 conditional_uses、卡片、槽位、角色、版本和证据；未知状态、缺正文、非法引用与缺实验的 measured 行被拒；用户观点不能冒充平台documented定义；单句校验不误伤0.5等数值或函数名称；默认 seed 不覆盖已验证记录。
- [x] 2. 运行 `python -m unittest tests.test_semantic_contracts tests.test_operator_semantics tests.test_template_library -q`，确认新增断言失败，而非环境导入失败。
- [x] 3. 实现上述契约，扩展 `OperatorSemanticRecord`/`TemplateRecord` 可选字段；旧模板标明 legacy/unreviewed，保持既有 skeleton 与身份。事实引用可支持数学定义，不自动支持经济推断。
- [x] 4. 重跑同一命令至 PASS，检查 `compile_operator_semantics` 合并后仍保留新字段，不只测试 dataclass。
- [x] 5. 记录交接；不把新默认数据写入真实 machine 账本。

### Task 2: 类型安全的多输入绑定与最小内核

**Files:** 新 `wqb/template_binding.py`、`tests/test_template_binding.py`；修改 `wqb/generator.py`、`tests/test_scheduled_candidates.py`。

**Interfaces:**
- `bind_template(template: dict, field_rows: list[dict], operator_rows: list[dict], scope: dict) -> dict`：返回 bound_expression、bindings、operator_provenance、operator_call_count；失败抛 `TemplateBindingError`。
- 每个 input_slot 保存 name、role、required_semantics、field_type、required_metadata、reduction。`reduction` 必须来自已验证算符定义，不凭函数名称猜类型。
- 新模板 `binding_version=2` 使用命名槽；旧 `{field}`/`{window}` 路径不改义。

- [x] 1. 写失败测试：不同语义的同名／同类型字段不可替代；跨 scope、缺必要单位／时点、VECTOR 粒度未知被拒；显式 `vec_avg`/`vec_count`/带参数归约只接原始向量一次；无法验证的前视时点失败封闭。
- [x] 2. 运行 `python -m unittest tests.test_template_binding tests.test_scheduled_candidates -q`，确认 RED。
- [x] 3. 实现类型／槽位绑定与调用计数；用明确占位符解析和合法标识符校验，不做全局任意字符串替换。生成器仅消费固定内核和批准的参数变化，未知参数位置不自动改写成窗口。
- [x] 4. 同一命令至 PASS；测试等价表达式仍使用原表达式＋设置 hash 去重，两个叙事不能重复 POST；调用次数按实际出现计数而非去重后的函数名。
- [x] 5. 记录交接，保留旧 VECTOR 修复与30上限回归。

### Task 3: 有界、增量、可取消的模型语义编译

**Files:** 新 `wqb/semantic_compilation.py`、`tests/test_semantic_compilation.py`；修改 `wqb/codex_ai_worker.py`、`wqb/ai_checkpoints.py` 及对应测试。

**Interfaces:**
- `prepare_semantic_job(root: Path, source_refs: list[dict], policy: SemanticPolicy) -> Path`：在 `machine/semantic_jobs/<digest>/` 写材料索引与知识任务 manifest，不创建研究 mission 或 WQB 权限。
- `compile_semantic_proposals(job: Path, executor_argv: list[str], policy: SemanticPolicy) -> dict`：返回 validated_operators、validated_templates、rejections、cache_status；不直接发布。
- 新 checkpoint_type `semantic_compile`；输出严格对象为 summary 与 proposals，proposals含 operators/templates，额外键拒绝。所有内容经 Task1/2 再验证。
- 增量缓存键包含材料内容摘要、结构版本、任务版本和影响输出的 policy；状态包括 ready/failed/cancelled，失败不会在重启中无界重跑。

- [x] 1. 写失败测试：相同输入重启模型调用一次；修改一个来源只重算依赖项；超过3机制／2分支被拒而非任意截断；未测用途不能写成 measured；来源中的“忽略规则／联网”仅为数据。
- [x] 2. 运行 `python -m unittest tests.test_semantic_compilation tests.test_codex_ai_worker tests.test_ai_checkpoints -q`，确认 RED。
- [x] 3. 实现短索引与按需材料包；只选择任务范围内的原始来源及知识资源，拒绝路径逃逸和凭据／敏感配置。必要定义和元数据不足时输出缺口，不自动抓取。知识任务 manifest 显式标明 kind=knowledge_compile，worker不混淆为研究任务。复用只读调用、medium推理和字节保护；不声称只读沙箱等于文件读取白名单。
- [x] 4. 为 `run_ai_checkpoint` 增加向后兼容的可选取消检查，知识任务的取消状态与研究权限独立。测试 Stop/取消发生在 worker前后均不发布；损坏缓存、材料摘要变化和无效输出保留证据并拒绝。重跑至 PASS，Repair schema及四句简报全部保留。
- [x] 5. 记录交接，禁止以测试为名调用真实 Codex worker或清零用量。

### Task 4: 一致资源发布、版本读取和崩溃恢复

**Files:** 新 `wqb/semantic_publication.py`、`tests/test_semantic_publication.py`；修改 `wqb/knowledge_paths.py`、`wqb/knowledge_clean_compile.py`、`wqb/knowledge_freshness.py` 及相应测试。

**Interfaces:**
- `stage_semantic_release(root: Path, proposals: dict, generated_at: str) -> dict`：生成不可变 `machine/semantic_releases/<release_id>/`，包含 operator_ledger/template_library、wiki渲染材料及其摘要。
- `publish_semantic_release(root: Path, release: dict) -> dict`：验证全部文件、来源和结构后，原子替换 `machine/semantic_release.json` 指针；该指针是语义资源唯一版本选择，不是第二套账本。
- `read_semantic_release(root: Path) -> dict`：一次读取并验证指针，返回固定版本资源 paths/digests/release_id；无指针的旧 vault 使用原始路径，指针损坏不得伪装无指针。
- `existing_machine_resource_path` 对 operator/template 路由到已选版本；一次读取多个资源的消费者必须共享同一 release receipt，不分别重读指针。

- [x] 1. 写失败测试：任一步写入中断保留上个有效机器版本；并发读只见完整旧／新版本；路径逃逸、符号链接、摘要冲突被拒；新旧入口均不写出另一套生效资源。
- [x] 2. 运行 `python -m unittest tests.test_semantic_publication tests.test_knowledge_paths tests.test_knowledge_clean_compile -q`，确认 RED。
- [x] 3. 实现有界锁、不可变 generation和原子指针；只保留最后有效资源作为故障读取证据，不能在损坏指针时悄悄 fallback。把直接语义写入入口改为经发布器提交，避免 canonical旧副本覆盖活动版本。
- [x] 4. 更新结构清洁检查和 freshness引用：生成物不伪造 raw 捕获日期；被任务引用的版本不自动清理。重跑至 PASS。人读 canonical wiki逐文件原子替换并带 release_id；工作流／Console只消费清单绑定版本，Obsidian已打开页面不承诺同时切换，版本不一致必须可见且可由 compile恢复。
- [x] 5. 记录交接；不删除真实资料、不迁移真实 vault。上述 Obsidian文件级原子边界须在操作文档显式说明，不以多文件原子假象交付。

### Task 5: 接入知识维护入口、wiki与阻塞通知

**Files:** 修改 `wqb/knowledge_compile.py`、`wqb/knowledge_vault_migration.py`、`wqb/knowledge_experience_compile.py`、`wqb/cli.py`、`wqb/console_jobs.py`、`wqb/console_state.py`、`wqb/console_server.py`、`wqb/console_timeline.py`；按现有边界扩展 `wqb/maintenance_notifications.py` 的知识任务通知入口；新 `tests/test_semantic_compile_console.py`；修改现有知识编译／通知测试；新增开发包装 `scripts/compile-semantic-knowledge.sh`。

**Interfaces:**
- `compile_semantic_knowledge_command(root: Path, config: dict) -> dict`：协调 Task3→Task4，输出 job/release/coverage/rejections/notification；禁止 WQB。
- 保留现有 compile-research-records 的原始记录总结能力；在用户启动的知识维护任务中使用明确 semantic 模式，迁移任务不得成为每次日常 compile 的必经步骤。
- `dispatch_knowledge_notification(job_dir: Path, now: str) -> dict`：只对未解决知识任务错误事件投递，去重、有界传输，不制造研究 case权限或自动改码授权。

- [x] 1. 写失败测试：研究后总结与资料更新后compile两种入口均可用；普通研究Start不触发全量语义编译或平台抓取；长知识任务取消后不发布；模型故障／来源缺口在Console显示确切原因与通知投递状态。
- [x] 2. 运行 `python -m unittest tests.test_semantic_compile_console tests.test_knowledge_compile tests.test_knowledge_experience_compile tests.test_maintenance_notifications -q`，确认 RED。
- [x] 3. 接入现有job而不新增研究推进按钮。配置3/2在参数解析处显式设置，跨模块通过policy传递；开发 `.sh` 包装设置并传入参数，日常用户仍通过Console使用，不要求CLI启动。
- [x] 4. wiki20/30呈现条件、竞争解释、角色、失败案例和证据状态；不输出全量机器账本，不新增历史wiki树。增加严格链接／证据等级／结构测试与失败通知去重测试，重跑至 PASS。
- [x] 5. 记录交接；真实知识内容不足要报告未完成覆盖，不用默认用途填出假完成状态。

### Task 6: 冻结快照、多机制选择与实际候选消费

**Files:** 新 `wqb/hypothesis_selection.py`、`tests/test_hypothesis_selection.py`；修改 `wqb/workflow_stage_adapters.py::create_start_snapshot`、`wqb/research_planning.py`、`wqb/research_rounds.py`、`wqb/source_bridge.py`、`wqb/workflow_auto_continue.py`、`wqb/cli.py::run_field_batch`、`wqb/generator.py`、`wqb/codex_ai_worker.py`、`wqb/run_readiness.py` 与相关测试。

**Interfaces:**
- `select_hypothesis_batch(snapshot: dict, candidates: list[dict], maximum: int) -> dict`：返回 selected/rejected/reasons，机制优先、数据语义／条件／算符职责次之，确定性稳定排序。
- `prepare_hypothesis_plan(run: Path, config: dict, metadata: dict, now: str) -> dict`：绑定release/snapshot、假设版本、全部字段槽、算符证明和模型选择收据；返回 scheduled_hypotheses及原始批次上限。
- 新 checkpoint_type `hypothesis_batch_plan` 只允许选择快照内列出的 hypothesis/version/binding IDs及既有允许参数；不允许模型写任意代码、修改阈值或读活动可变vault。
- v2 source metadata记录 `hypothesis_bindings`；v1 exact_field_id/template_provenance保持兼容。冻结快照新增operator rows、semantic release和必要字段语义，原有 snapshot按版本分流。

- [x] 1. 写失败测试：同等可行性优先不同机制，不把窗口变化当新族；字段不可用时少选，不乱补30；模型选不存在ID、改schema、改scope被拒；refresh／新compile不改变旧run快照。
- [x] 2. 运行 `python -m unittest tests.test_hypothesis_selection tests.test_research_planning tests.test_scheduled_candidates tests.test_research_rounds tests.test_source_bridge -q`，确认 RED。
- [x] 3. 接入选择器与Task2绑定器，并把实际决定传到生成器；既有单模板模式作为v1兼容，不用advisory摘要假装已执行新模式。修改快照行选择与readiness，确保多输入的所有必要字段都真实冻结，而非只冻结主字段；如果快照行数上限无法容纳依赖，则该模板不可执行，不能静默截断必要字段。
- [x] 4. 测试计划先于POST落盘；重启复用同版本计划；不同叙事等价模拟只提交一次；剩余7次时最多7、零候选自动换合法方案，否则明确通知。保持模型缓存、防旧POST重放与当前轮数限制，重跑至 PASS。
- [x] 5. 记录交接，不改成熟Repair协议；假设引用可作为其支持材料，但不能扩写四句正文或改变当前权限。

### Task 7: 闭环验收、兼容迁移与交付

**Files:** 新 `tests/test_economic_hypothesis_acceptance.py`；修改 `tests/test_workflow_acceptance.py`、`tests/test_project_architecture.py`；更新 `docs/operations/user_workflow_manual.md`、根 `milestone.md`、`todo.md`。

- [x] 1. 先写失败集成测试：临时raw材料 → 假模型条件编译 → 一致发布 → 多机制计划／多字段绑定 → 假平台Scout → 既有Seed/Discovery/Repair／检查 → 研究记录 → 增量再编译；显式断言所有新记录能追溯，未测结果不升级为经验。
- [x] 2. 运行 `python -m unittest tests.test_economic_hypothesis_acceptance tests.test_workflow_acceptance -q`，确认 RED。包含模型失败、429、Stop、未知提交、零候选和中断恢复场景。
- [x] 3. 补齐接口连接，禁止在测试中手工复制artifacts绕过真实入口。迁移只在临时vault证明旧记录可消费、语义待补充不伪装ready；旧资格证据与活动研究原样保留。
- [x] 4. 运行完整 `python -m unittest discover -s tests -q`、`python -m compileall -q wqb tests`、`git diff --check` 和架构／入口文档测试；新鲜复审后冻结源码做正式维护证明，不用旧1443测试结果代替当前验收。
- [x] 5. 在原Console进程确认空闲后加载新版本，验证revision/state/actions及知识job／研究计划的显示与通知。默认只读加载验收，不按Start、不调用真实WQB／模型、不增预算。真实知识维护若未获授权，明确保留为待启动，而非宣称真实vault已完成升级。
- [x] 6. 给出文档与操作说明，标明旧运行使用旧快照、新任务才用新语义。更新架构与Latest handoff：测试证据、当前阻塞、精确下一操作、未提交文件；没有已知可行动代码缺口才宣布工程交付。

离线工程验收：1679 tests / 0 failures / 2 Windows symlink skips；独立复审 PASS；加载 Console revision 与本地一致。证明在根 runs/maintenance_acceptance/20261014-economic-hypothesis.json。旧运行的维护证明更新须单独明确授权，尚未进行；因此不能将以上工程验收称为旧研究已恢复。真实 vault 语义编译也未执行。

## Dependency And Execution Choice

依赖：Task1 → Task2/3 → Task4 → Task5/6 → Task7。Task2与3可在契约固定后分工；Task5与6涉及共享入口文件，不同时写同一模块。

推荐选择子代理逐任务执行，理由是类型绑定、资源发布和计划消费各有独立风险，阶段验收有助于控制上下文与防止再次“页面完善但执行未接入”。也可主代理顺序实现，最后独立复审，成本更低。无论选择哪种，都从根todo恢复主线，子代理≤medium，不把聊天记忆当状态。

## Acceptance Coverage Map

Spec验收1→Task1/4；2→Task1/3；3→Task2；4/5→Task3/6；6→Task6；7→Task3/4/6；8→Task5/6/7；9→Task7；10→Task5/7。

本计划只安排实现与离线证明，不承诺策略收益或合格Alpha产出，也不扩大真实平台调用、知识抓取、模型调用或最终提交权限。
