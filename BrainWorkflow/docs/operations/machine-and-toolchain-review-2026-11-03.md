# Machine 知识库与工具链精简评估

日期：2026-11-03。范围：本地文件统计、现有代码与验收证据；没有修改程序、删除资料、抓取平台或运行研究。以下优化均为建议，未获实施批准。

后续决议：用户另行批准退役旧 AI Repair 的执行能力，保留研究证据；实施与验收见 `../superpowers/plans/2026-11-03-retire-ai-repair.md` 和根 todo.md。本报告的体积统计仍是清理前测量，不表示其余 machine/gate 优化已获批准。

## 结论

1. machine 共 1,322 个文件、2,527,563,026 字节，约 2.53 GB（十进制）。其中七个文件占 99.54%。主要问题不是算符/模板过多，而是完整目录快照和逐项报告重复保存。
2. 不应通过减少全平台字段或只保留 USA 数据解决体积问题。应该去除存储重复、按内容复用清单，并让查询只读取当前任务需要的记录。
3. 一些限制本来用于模型输入或安全恢复，却扩散成了知识库读取、研究探索和维护完成的硬门槛。建议分离数据事实、研究假设、执行能力和提交资格。
4. 不增加 Agent 框架，不重写 Orchestrator；优先修改资源存储/查询入口和验证接口。旧运行与证据引用必须兼容。

## 当前结构与用途

```text
knowledge/machine/
  data_ledger.jsonl          字段、scope 覆盖、来源及使用历史
  operator_ledger.jsonl      根目录算符资源，包含兼容投影
  template_library.jsonl     根目录模板资源，包含兼容投影
  scope_matrix.jsonl        市场、delay、universe 等范围信息
  benchmark_rules.jsonl     研究判定与评分规则
  research_records.jsonl    已汇总的研究记录
  mechanism_evidence.json   按经济机制整理的实验观察
  source_index.jsonl        原始资料的登记与完整性索引
  freshness_manifest.json   更新期限与资源就绪信息
  semantic_release.json     当前选中发布版的指针
  semantic_releases/        不可变的发布资源与发布证据
  semantic_jobs/            知识编译任务、资料包、结果、清单、证据
  reports/                  覆盖、缺口等机器报告及短 Markdown
  decisions/                研究选项、决定及相关产物
  candidate_evidence/       候选 Alpha 检查缓存与 SELF 池版本
  previews/                 有界的资源预览，不是完整知识权威
  *.guard / *.lock          并发控制，不是经验内容
```

根目录算符/模板文件与发布目录并存属于兼容结构，不能仅凭名称删除。读取方应经统一资源入口选取发布版本，避免自行混合根表与不同 release。

| 区域 | 实际体积 | 文件数 |
| --- | ---: | ---: |
| semantic_jobs | 2,096.08 MB | 1,281 |
| reports | 229.62 MB | 10 |
| 根目录文件 | 201.76 MB | 14 |
| previews | 45.36 KB | 4 |
| decisions | 37.90 KB | 8 |
| semantic_releases | 17.27 KB | 3 |
| candidate_evidence | 88 B | 2 |

## 体积的真正来源

- 三份 `semantic_jobs/<plan>/inventory.jsonl` 分别约 696.26、696.66、692.99 MB，合计 2,085.91 MB。
- 三份详细覆盖 JSON 分别约 76.53、76.52、76.52 MB，合计 229.57 MB。
- `data_ledger.jsonl` 为 200.48 MB，记录 153,513 条范围记录；同一字段跨范围重复出现，共有 88,562 个字段身份。
- inventory 的 occurrence 保存了完整原始行和 ledger 行，不只是身份/引用。抽查首条，occurrences 占约 4,143 个 JSON 字符，内含约 2,342 字符的原始行及 1,262 字符的 ledger 行。
- 每份计划都在自己的目录保存完整 inventory。计划身份还包含代码合同、配置和预算；改变计划不等于所有字段事实都发生了变化，但当前存储仍会产生完整快照。
- 覆盖报告再次展开全部目标、状态与重复错误文字；多个历史报告又重复这一结构。
- `full_semantic_compile.py` 使用 `b''.join(...)` 构造完整 inventory 字节串；磁盘膨胀和 Python 对象/序列化副本共同增加峰值内存。不能只做磁盘压缩便宣称内存问题已解决。

只读、内存内 Gzip 实测（没有改写原文件）：

| 文件 | 原始 | 压缩后 | 节省 |
| --- | ---: | ---: | ---: |
| 最新 inventory | 692.99 MB | 62.62 MB | 90.96% |
| data ledger | 200.48 MB | 5.74 MB | 97.13% |

压缩说明重复度很高，但不提供随机检索能力，也不减少完全解码后的对象体积。

## 完整工具链

这里的“工具”主要是 Python 服务模块、API 客户端及受控子进程，不是每一步都调用一个 AI Agent。

| 环节 | 主要实现 | AI 与约束 |
| --- | --- | --- |
| 点击入口与界面 | 外层启动器、desktop/desktop_application、React/TypeScript/WebView2 | 用户选 Option Card、Start/Stop；新 EXE 已隔离验证，正式入口尚未迁移 |
| 本地交互 | console_server、console_api、console_start，JSON/SSE | 持久化命令、状态投影；不是依靠聊天上下文推进 |
| 预检与选题 | start_preflight、run_readiness、research_planning | 使用本地资源、激励与范围；不隐式抓平台 |
| 初始研究准备 | preplanned_start、initial_research_planning、initial_model_worker | 每 lane 一次受控 Codex 任务，生成假设/字段角色/条件/实验树 |
| 模板编译 | hypothesis_design、hypothesis_template_compiler、template_binding、resource_evidence | 严格结构、类型、来源和 AST；不是执行 AI 任意代码 |
| 并行调度 | research_group、research_group_driver、research_tree、tree_runtime | 默认两条 lane，冻结分支后脚本按实测结果路由 |
| 回测传输 | CLI 服务、client、simulator、请求节流策略 | multisimulation 分块；轮询、429 冷却、已有身份恢复 |
| 安全监督 | owned_network_deadline、runtime_control、daily_simulation_budget、source_run_lock | Stop、总超时、所有权、共享日预算、未知 POST 不重发 |
| Scout/Seed | experiment_tree、research_seed_stage、seed_policy、benchmark | 正负信号/双支/无信号/回退；Sharpe > 1.25、turnover < 0.40，评分后最多 8 seeds |
| Discovery/Repair | discovery_runtime、repair_search、repair_scheduler、repair_runtime | 有限确定性搜索；新预计划模式没有层间或 Repair 模型调用。旧运行保留旧路径 |
| 正式检查与候选 | checker、candidate_evidence、pending_check_recovery | 便宜的基线先行，之后 SELF/PROD；检查不完整不合格，最终提交单独授权 |
| 研究沉淀 | research_record、mechanism_evidence、interaction_memory | 保存实测/失败/未知与 lineage，不把相关性当因果 |
| 知识维护 | 本地 capture 工具、knowledge_contracts、data_ledger_compile、knowledge_maintenance | 平台抓取是单独维护；日常研究不做全库重编 |
| 语义解释与发布 | full_semantic_compile/execution/model_worker/coverage、semantic_compilation/publication、knowledge_experience_compile | 单独的有限模型任务，验证后走既有发布边界，编译人读 wiki |
| 故障维护 | recovery_cases、maintenance_notifications、maintenance_resolution、runtime_boundaries | 可恢复问题用脚本；代码问题事件投递维护窗口，不能凭通知自动获修复授权 |

新预计划树耗尽后会记录并结束，不再用旧的连续轮次重放同一棵树。持续自动生成新树属于另一个需要对齐的合同；“该树执行完”不等于“已找到可提交 Alpha”。

## Gate 应怎样区分

### 必须保留

- Stop、原有授权、共享日预算与时长限制。
- 未知 POST 的身份与扣费证据；不得盲目重发或退款。
- 表达式类型合法、禁止未来信息、字段/设置与回测身份一致。
- 原始来源真实且引用可验证；不能把模型猜测记成官方事实。
- 不完整检查不能进入提交清单，SELF/PROD 有效性与最终提交授权。
- 用户确认过的 Seed 硬阈值。它与 Scout 的“是否值得继续探索”应是不同层。

### 应优先优化，而不是简单删除

| 当前限制 | 问题与建议 | 需保留的保护 |
| --- | --- | --- |
| 原始材料 2 MB 上限 | 超大本地 catalog 被当作模型输入拒绝；应本地流式解析、按行/字段引用，仅模型提示保留有界摘录 | 原始文件、行、scope、generation 的完整性与来源验证 |
| 字段缺部分语义便整体不可用 | `_coverage_field_supported` 仍要求 available_at 或 timing_contract，VECTOR 要 grain；应按具体特征和执行需求分级，未知不是编造也不应统一等于不可探索 | 不能用采集日期伪装可交易时点；无法证明防未来信息时仍不能执行相关操作 |
| 算符描述精确匹配与 Repair 两种 invariant | 自然语言改写会拒绝等价定义，支持范围窄；应转成版本化签名/属性/规则注册表并测试，而非逐字比英文 | 经济方向、类型、数学性质与当前父表达式必须验证，不能仅信 preserves_direction=true |
| 暴露/频率必须具有特定事实键 | 可能把可检验的经济假设要求成官方布尔事实；将“公式合法”与“假设待检验”分开，允许声明条件的 Scout 对照实验 | 不准用 is_active 冒充暴露；Repair 不得偷换机制或引入不相关字段 |
| 每节一句话泛化到所有知识 | 简报短是合理的；完整算符解释、条件与知识卡不应因标点/展开解释被拒。区分运行简报与知识资料 schema | 有界输入、结构与出处，不能借此无限增加模型上下文 |
| 所有资料统一 90 天 | 活动/字段可用性与稳定的算符定义变化速度不同；可讨论按资料种类、风险、变更证据分级 | 当前 90 天是已确认政策，未经批准不变更，更不伪造捕获日期 |
| 数据集按一批字段一起验证 | 一个无效选择可能拖累整组；先评估每个字段的特征能力，再选可用字段组合 | 已冻结或显式选中的无效引用仍应阻断，不能悄悄替换 |
| 多层反复读相同来源并验证 | 共享同一不可变快照的验证结果，只在依赖变更时重算 | 预算/Stop 实时检查，选定来源变动和并发变更必须重新验证 |
| 任意源码变化令旧证明/任务合同失效 | 整个模块字节变更会让无关缓存也失效；按语义合同/依赖闭包验证，旧答案通过当前校验后复用，同修订维护案例共享测试证据 | 不能伪造证明有效或跳过必要审批；实质合同/策略变化仍失效 |
| 每个案例重跑整个测试套件 | 当前完整回归约 11.5 分钟；同一次稳定维护可集中跑一次全套，各子改动跑定向测试 | 发布前全套、真实组合测试、源码前后摘要仍保留 |

GROUP 未支持等情况属于编译能力缺口，不是删除 gate 就能获得支持。固定正整数窗口已由项目规则支持；不应退回“只准官方示例数值”的限制。

真实只读探测的 298 个缺口中，296 个是超出来源读取上限，2 个是已选摘录过期。这不证明修复文件读取便会得到 296 个可执行数据集，但说明剩余问题不能仅归因为“服务器资料过期，全部重抓即可”。应先消除本地消费障碍，再确定必要抓取。

## 建议的精简顺序

### A：先精简存储与边界，推荐

1. inventory 与执行 plan 分开寻址：计划仍独立冻结预算/权限，但内容相同的清单只存一份；之后可按数据集分片或记录差量。
2. occurrence 保存原始行定位/哈希，不嵌入完整 raw 和 ledger 行；公共 dataset/字段释义只保留一份，scope 与使用历史分开。
3. 覆盖报告默认只保存计数、错误码及引用，逐项状态用有界 JSONL/分片；完整展开作为按需导出，不在每次维护保存一次。
4. 历史不可变产物经依赖审计后压缩归档；新读者版本化兼容旧引用。不能直接改名、删掉仍被 run/job/release/proof 引用的文件。
5. 首先修本地流式材料读取和统一验证结果接口，再讨论 freshness、语义能力分级；不扩大模型权限或删除安全 gate。

### B：如果查询仍慢，再规范化索引

可将机器字段/scope/使用量与查询索引逐步改为 SQLite 等结构化存储，保留 JSON/JSONL 导出与旧运行读取适配。它解决检索和重复列，迁移成本高于 A；现在不建议先迁库或引入向量库/RAG、LangGraph、新多 Agent 框架。

## 工具数量也应精简，但不按文件数一刀切

- UI、CLI 应调用同一服务，而不是维护两套阶段推进规则。CLI 可以作为内部可测试入口，不要求用户使用命令行。
- 初始研究、知识解释、旧版 Repair 的 worker 是不同合同的适配器；可共享进程启动/取消/日志实现，不能合并成不验证任务身份的万能执行器。
- 通知、边界、恢复案例应有统一可读错误投影；保留不同授权语义，不再让每种失败都成为一套新控制流程。
- 旧运行代码先隔离为兼容层、停止新增分支；只有确认无活动引用且通过迁移/恢复测试后才删除。
- 优先处理占 99.54% 的七个大文件及重复验证，不优先删除几十 KB 的指针、guard 或配置。

本报告是优化讨论的依据，不是放松 gate、删除历史、抓取资料、增加额度或部署的授权。

## Nov4复核：实际触发与尚未评估

本节重新读取Nov3实际审计的持久化结果，不声称重新编译或重新验证了今日全库；未调用平台或模型。

- `output/desktop-validation/start-resource-probe-20261103.log`：USA D1 TOP3000资源探测0可用/298缺口，其中296是本地来源超过2,000,000字节读取上限，2是Jul30摘录超过90天年龄政策。计数是缺口项，不等于298个独立字段。
- 全量计划92557c：88,670个身份中88,441 blocked/229 prepared。流式重读inventory：88,441次no_verified_material、88,670次unverified_occurrences；后者与前者重叠，且prepared目标也可能含未验证的额外出现位置，不能相加或据此把所有目标判无效。
- 计划source diagnostics有六条：Jul30全量data_fields.jsonl超读取上限；Jul29 data_fields.jsonl及Jul29/Jul30 operators.json只作为未索引raw存在；Oct11 incentive_snapshot.md及operators.md的索引摘要不一致。仅凭这些错误不能确定资料被篡改或必须重新联网抓取，应先核实索引与实际内容。
- 当前合同解释结果0/88,670：229个准备目标尚未执行解释，计划model_call_budget=0/execution_authorized=false。不是229次模型失败；cached_jobs是任务材料复用，不能当成已有可信解释答案。
- knowledge maintenance的11条health问题都指向同一份Oct13用户研究建议笔记：九项元数据缺失，加未收录source index和无wiki/index引用。它阻止该次维护显示completed，不是11个坏字段，也不能等同于直接阻断所有研究。
- 单位、频率、VECTOR粒度、算符英文描述、Repair数学性质/暴露等存在代码级限制，但本轮没有其全库实测触发计数。前置来源gate挡住后的not_evaluated不能当作通过或失败。

后续gate设计必须分别记录：发生阶段、错误代码、目标身份、直接原因、是否完成评估、影响范围；不将工程/来源/解释/策略质量混成一种不可用状态。

Nov4 Repair维护期间再次直接调用当前`preplanned_start._local_resources`，限定USA D1 TOP3000、1个资源组、仅本地读取：usable_lanes=0、receipts=0、diagnostic_count=298；首两项仍为Jul30来源超龄，其余抽样项仍为来源超读取上限。没有更新raw、发布时间、规则额度或旧运行。这证明Repair默认规则的离线集成通过并不等于真实Start已可用；来源读取/索引主线仍待实施，SQL存储提议也未被当作已交付。

## Nov4来源维护实测（未发布）

- 新增的是可重建的SQLite字段目录，不是SQL事实库。Jul30原文208,766,843字节；目录52,592,640字节、85,569条身份，只保存偏移、scope和摘要。原文、manifest、ledger、source_index和release摘要保持不变。索引命中仍验证原文字节，不能替代来源年龄或语义证据。
- 单字段同一proof读取由1.688秒降为0.406秒；随后精确查询进一步改用参数化身份索引，不再遍历全部SQL行。完整库存仍需全量扫描，不能以单字段速度承诺全库耗时。
- 今日只读health：73份raw、9页wiki、结构clean；0条阻塞、11条本地设计笔记整理警告，耗时1.053秒。health仅证明结构/元数据合同，不证明资料新鲜、内容摘要正确或可研究。
- 旧Oct11算符文档的修复预检明确返回`need_fresh_capture`：缺保留的`operators.json`，无法证实旧payload哈希。活动快照摘要同样未获解释；两份资料不盲改、不删除。Jul29/30字段资料仍超过90天，不伪造新采集日期。
- 新库存保存紧凑row_ref与scope，预算不同但内容相同的计划共享库存；执行权限、原用量及旧plan-local读取不变。覆盖报告v2默认仅汇总和`targets_ref`，详细JSONL按内容共享；Python调用可用`detailed=True`读取本次逐项结果，磁盘报告仍保持紧凑。
- 旧大库存尚未删除。引用保护清理、全量验收和实际资源就绪是分开的检查；未经证实的删除与发布不会由上述局部通过推导出来。
- 实际新计划`53e7c20b`：库存184,196,874字节、88,670个身份，229 prepared/88,441 blocked。准备35.149秒。再次准备及两次覆盖验证共63.886秒，计划/库存引用不变、库存与共享明细均未重写、任务目录增加0。覆盖JSON仅3,456字节，逐项明细55,246,613字节按摘要单独保存；model_calls=0/research_ready=false。Jul29/30原文、source_index、data_ledger、semantic_release在重复验证前后摘要一致。
