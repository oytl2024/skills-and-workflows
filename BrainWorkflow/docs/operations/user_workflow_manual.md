# BrainWorkflow 操作指南

本指南对应本地 Console 的日常研究路径。项目维护和真实策略运行是两条独立工作线；Console 的持久化状态是运行事实，Codex 对话不是状态存储。

## 预规划桌面版验收说明

2026-10-23：新版正在离线集成，尚未替换下述已部署入口。构建产物存在不等于已部署或获得研究授权；以根 `todo.md` 的整体验收记录为准。

新版日常操作仍为：选择研究方向，点击 **Start**；需要暂停时点击 **Stop**。左右箭头和 `1/N` 仅切换查看工作流，不启动或停止某一路。Scout、Seed、Repair 标签及树节点只查看事实，不是推进关卡的按钮。

初始规划会读取已认证的本地字段、算符、模板和历史证据，每一路调用一次受限 AI 生成结构化假设与整棵实验树。之后脚本按实际回测结果分叉、保留较优内核，再执行有限 Repair 搜索；不会在每层实验后调用模型。原始资料不足时保持未知，不虚构字段含义、频率或可用算符。缺少可靠 Repair 编辑依据会显示搜索耗尽及原因，不把它解释为经济机制已被证伪。

维护配置 `research_policy.preplanned_tree_version=1` 才启用新路径；默认并行数为 2，可扩展到更多路，但不会按路数扩大共享配额。`repair_search_policy` 可提供经验证的有限设置实验：必须绑定当前认证的来源和数据特性，不能把项目选择宣称为平台官方参数范围。首版 Start 不接收任意 transformation 规则；未提供可信规则时默认记录规则耗尽。这是当前真实能力边界，不会退回运行中临时询问模型。

界面应立即显示命令处理中，再显示后台接受、任务状态或行内拒绝原因。断线重连只查询同一命令，不自动重复发送 Start。停止后保留正在对账的提交身份、历史用量和结果；重新 Start 不增加预算。关闭软件窗口不会停止后台研究，暂停必须点击 Stop。共享每日 4,000 次按实际回测子任务计数，不是每路各 4,000 次；冷却、时长、恢复次数和最终 Alpha 提交授权独立。

Scout 详情区展示基准/处理两组的表达式、假设、设置、实际 Alpha ID 和信号，缺少结果时留空或显示未知。Seed 展示严格门槛筛选后的保留内核；Repair 展示逐次修改及接受/回退结果。回测正向相关不代表经济因果已证明；进入候选也不代表获准提交。

## 打开软件

### 恢复历史批次

旧批次没有运行授权记录时，维护端必须先按用户确认登记一次范围：绑定原 source、计划摘要、原始设置与剩余表达式，登记后仍保持暂停。此后只需点击 **Resume workflow**，不需要回到 Codex 发启动命令。系统先维护过期知识，再等待平台冷却，优先收集已提交结果，最后以 multisimulation 续跑原计划。**Stop workflow** 始终优先；重启和重复点击不扩大范围、不清空消耗。

页面显示原计划总数、已检查数和剩余数。剩余身份数与 HTTP 重试次数不同：只允许原剩余身份，明确拒绝后的重试受最多三次恢复和运行时限约束；未知提交结果必须先对账，不会盲目重发。旧历史请求次数仍标记未知，不视为可用配额。旧批次完成后停止，不代表已得到可提交 Alpha，也不会自动生成新批次或提交 Alpha。

双击工作区根目录的 `BrainWorkflow.vbs`，或项目里的 `launch-desktop.vbs`。这会打开独立的 Edge/Chrome app-mode 窗口，并复用已启动的本地后台；它还不是打包后的原生 Windows 安装程序。打开窗口本身不会调用 WQB 或开始回测。启动失败时查看 `runs/desktop/startup.log` 和 `backend.log`；终端诊断入口是 `launch-desktop.cmd`。

项目架构看板是另一入口：双击 `management/Open Board.cmd`，在 Signboard 的 **Project architecture** 卡片打开工作流图。它只解释项目，不控制正在运行的 Alpha。

## 每天怎么用

### 每日回测额度

新版预算以北京时间（Asia/Shanghai）每天 00:00 重置，工作区内所有受管研究、Scout、Discovery 和 Repair 共用每天 4,000 次 simulation 提交尝试。一次 multisimulation 包含几个子策略就扣几次；查询结果不扣，提交失败或结果未知也不退款。这不是平台承诺的配额，平台 429 仍独立处理。

Workflow Progress 显示 Today（当天用量）、Lifetime attempts（保留的累计用量）和 Next reset。额度不足时自动等待，跨天后在原有时长、恢复次数和 Stop 约束内继续原任务，不需要新增额度按钮。停止后不会因跨天自行开始；应用重启后使用原 Resume workflow。运行时长耗尽仍按下面的时长授权操作处理，不因每日重置而延长。

旧运行必须先由已批准的本地维护迁移，累计历史只保守计入激活日一次，并标明是迁移用量而非伪造当天发生时间。未迁移的旧运行和 original-only 批次仍保留更严格的旧上限与身份范围。部署/迁移验收状态见工作区 todo.md；文档不代表旧运行已激活。

运行时长耗尽时，普通 **Resume workflow** 不会增加预算。请在 **Workflow Progress** 选择新增 6 或 12 小时，再点击 **Authorize extension and resume**。这会保留累计用时、回测次数及其他上限，只增加明确授权的运行时长；旧请求不能覆盖新的 Stop，重复点击不会重复增加额度。维护阻塞仍需先修复并验证。详情见 [Runtime Renewal](runtime-renewal.md)。

1. 选择一张 **Research option** 卡片和可用 scope，点击 **Start workflow**。后台先执行所选 scope 的本地预检；只在缺少可编译字段总账时从已有 raw 修复一次，就绪时不重编。预检通过后才创建研究运行并自动推进。这一选择授予该次研究的受控 live simulation 权限；不会授权联网抓取知识或最终 Alpha 提交。
2. 后台自动执行合法的阶段、限定批次、检查结果、等待平台冷却并在预算内恢复。**Runtime Timeline** 显示阶段，**Current Work** 显示当前动作和原因，**Strategy Progress** 显示每条计划/在途/已检查策略。页面通过本地事件流和轮询自动更新，不需要手动刷新或逐阶段点击。
3. **Stop workflow** 是可恢复的暂停：先写入暂停意图，等正在发出的 simulation POST 结束后才确认；确认后不会再开始新的 simulation POST。已提交的 progress URL 和证据会保留。需要继续时点 **Resume workflow**。它只使用启动时保存的授权，不接受表单临时提升 live 权限。
4. 平台 429 和 `Retry-After` 在可恢复预算内自动冷却、恢复已有在途或计划队列。超出预算、知识过期、凭据失败或证据损坏时，**Current Work** 显示阻塞原因和证据；此时不要求你点击内部 gate 或单独确认限流。把阻塞交给项目维护任务修复并写入测试/规则，然后继续运行。
5. 出现候选审批时查看硬性指标、相关性、表达式和证据，再作人工决定。候选审批与最终 Alpha 提交是两个不同授权；系统不会自动提交 Alpha。

**Preparing research locally** 表示尚在准备，不是正在回测；此时仍可 Stop。**Research preparation blocked** 会列出精确资料路径、原因和维护消息投递状态，不创建半个研究运行。过期平台事实不会因为本地 compile 被伪装成新事实；重新联网抓取仍是你在维护窗口单独提出的任务。研究结束后也可启动 compile，把研究记录沉淀为可复用经验。正常研究启动不会每次全量抓取或重编知识库。

新研究的 readiness 与旧运行的 readiness 分开：旧批次通过或已完成不代表新研究已就绪。启动前显示未核验是正常状态，Start 会自动预检，不要求手动点击内部 gate。

## 已合格但未提交的 Alpha

完整硬性检查通过且平台身份为 `UNSUBMITTED` 的 Alpha，检查器会将 Alpha ID、表达式、设置、原始指标与检查响应、检查时间和有效期写入 `knowledge/machine/candidate_evidence/`。这是机器证据，不生成巨大的 Obsidian 表格。

在有效期内再次查看或恢复同一 Alpha 时，先读取并验证本地证据，不重复请求 SELF/PROD correlation。默认有效期为 24 小时，客户端显式配置不能超过 7 天；过期不是 Alpha 被删除，而是不能再把旧检查当作当前可提交证明。文件损坏、表达式/设置身份不一致或显式失效时不复用。平台规则和账号已提交组合可能变化，因此不承诺缓存永久有效，也不代替最终提交授权。

若检查在途期间证据被标记失效，旧检查不会覆盖新失效状态；诊断记录显示 `persistence_status=superseded`。失效保留原始 Alpha 身份和证据，只有在失效后重新开始的检查才能恢复缓存复用。启动进程本身失败或超时也会生成维护回执，不要求用户反复点击；过时的 Start/Resume 和完成回调不能覆盖较新的 Stop。

## 屏幕怎么看

| 区域 | 含义 |
| --- | --- |
| Objective and Gate Summary | 本次研究方向、数据就绪度和关键阻塞。 |
| Runtime Timeline | Orchestrator 的持久阶段状态；Scout 和 Seed 概念上分开，但运行状态共用 `scout_seed`。 |
| Current Work | 目前正在做什么、下一步、冷却或阻塞原因及证据路径。 |
| Decisions and Approvals | 选项、开始、暂停/恢复、人工候选审批。 |
| Strategy Progress | 按表达式/Alpha 显示计划、模拟和检查结果；不虚构平台进度百分比。 |
| AI judgments | 自动创建的关键判断任务和 `pending/running/completed/failed` 状态。只有 `completed` 且有输入、输出证据才代表模型实际执行。 |
| Recent Jobs | 后台任务的持久记录，用于诊断；不是日常推进按钮。 |

Console 仅在本地浏览器与本地后台之间刷新状态。页面的 `server_revision` 不匹配时会禁用旧按钮并自动重载；无需在 Codex 对话里询问每一步发生了什么。

## 知识维护与经济假设

本节的既有 V2 功能曾通过离线闭环验收及 Console 加载版本核对；这不代表后续 M1 改动已重新部署。真实知识库尚未执行本轮语义编译，离线验收不代表真实资料覆盖完整或平台回测通过。旧后台不会因磁盘代码更新而自动获得此能力，交付以加载版本与验收记录为准。

知识维护有两条独立路径，不是研究每一步都要点击：

- 已完成研究后，点击知识维护区的 **Summarize research records**，整理已有研究记录与案例；这不会联网补资料，也不会把未完成实验当成有效经验。
- 单独要求更新平台资料并完成抓取后，点击 **Compile semantic knowledge**，从已有本地来源提炼算符条件用途与模板假设。后台按限定目标增量处理、验证和发布；未覆盖部分仍显示缺口，不假装全平台知识已完成。新研究须通过更新后的知识预检，普通 Start 不会全量重编。

查看知识维护状态与 Runtime Timeline：`running` 表示任务在执行，`completed` 表示本次发布成功，不等于所有资料都已理解；`blocked` 显示确切错误、证据和维护消息投递状态。取消知识任务只影响这次知识编译，不改变研究的暂停意图、权限或用量。模型通过本机只读 Codex CLI 执行，推理强度不超过 `medium`，不保证当前聊天页出现消息。

每个新模板保存七句可审核的假设卡：数据含义、机制、条件、竞争解释、区分预测、算符职责、否定标准。默认每个触发点最多三个机制、每机制两个条件分支。整批覆盖不同机制，单个表达式只保留必要算符；缺单位、观察粒度、可用时点或权威签名时报告不可执行，不由 AI 猜测补齐。显式时点校验不等于已经证明所有历史数据的 point-in-time 对齐；真实平台的数据规则与检查仍是独立证据。

长研究报告通过短章节索引与经摘要校验的完整本地副本供模型按需阅读，不把整份历史塞进提示词，也不截断原始记录来伪装完整学习。取消后的相同内容任务保持终止；再次启动会显示明确阻塞和维护通知，而不是暗中清缓存重跑模型。

`raw` 保存来源，`machine` 保存程序资源与任务证据，人读内容在 `wiki/20_data_semantics.md`、`wiki/30_template_and_operator_patterns.md` 与既有研究案例中。平台定义、待检验假设、实测经验有不同证据等级；样本内改善不自动成为稳健规律，降低换手也不等于已经测出交易成本。

机器算符与模板通过同一不可变版本发布，新研究冻结该版本、全部字段槽与实际采用的模型选择；之后更新知识不会改变旧任务。Obsidian 页面逐文件原子替换并标明版本，不承诺多页同时切换；中断导致页面版本不一致时重新运行知识编译修复，不手工复制另一套账本。

### 结构化模板 M1 的边界

M1 是受限的知识维护提案能力，不是新的研究运行器，也不增加日常推进按钮。当前工程验收与真实资料就绪分开记录在工作区 `todo.md`；资料缺失时不能宣称已经可用于真实研究。

历史来源合同（2026-10-15）曾缺真实编译对；2026-10-16 已用下述实际来源闭合该项缺口。以下支持范围不是全平台语义覆盖、后台已加载新版本或旧运行可恢复的证明；当前离线工程验收见工作区 `todo.md`。

窗口策略更新（2026-10-16，已通过离线审查）：显式 `ts_delta_project_window@2` 将正整数窗口标为项目约束，而不是平台完整参数域的声明；仍核验算符身份、含义、类型及文档中的相反限制。默认 `5/22/122/252` 是研究约定，不是白名单或自动参数网格，后续可有依据地选择其他范围内的值。旧 `ts_delta@1` 的原证据要求保持不变。编译器、直接绑定和覆盖审计均执行新规则的边界。

真实资料验收（2026-10-16）：已保存的官方字段/算符/时序资料加上单独记录的用户极性假设，经真实模型生成结构化假设并确定性编译出 `-snt_buzz` 与 `-ts_delta(snt_buzz, 5)`，附一份基准/处理实验计划。两者均为 `unreviewed/scout_only`，尚未发布、回测或授予研究权限；负向编码是待证伪假设，不是平台官方定义。缓存重放不新增模型调用；可选 GROUP 仍不支持。这不代表 M2/M3 或当前 Console 已部署完成，实际状态以 `todo.md` 为准。

手动提交对账：`reconcile_manual_submission(...)` 校验已索引用户报告与本地表达式/设置身份，保留失败与 PENDING 检查，不补造审批队列；重复报告不重复计数。`e76lZY3N` 已登记为用户报告的手动提交，真实提交时间未知、平台状态未在线核验。新增已提交 Alpha 会使旧 SELF 缓存资格失效，但不会自动重查相关性或恢复研究。

| 来源支持范围 | 可接受证据与仍然存在的限制 |
| --- | --- |
| 资源版本 | `resource_contract_version` 由生产端显式选择；缺省为 `1`，只接收严格整数 `1`/`2`，拒绝 bool、未知版本及资源封装与 evidence pack 不一致。版本号本身不授予信任；旧字段缺省序列化保持不变。它不同于既有假设的 `binding_version=2`。 |
| 字段时点 | 版本 `2` 可用已验证的 `timing_contract` 代替缺失的 `available_at`；初始规则仅为 `regular_delay_1@3`。必须同时证明平台自动 Delay-1 政策、正面点名的 Regular 字段及 cutoff 分类、原始字段捕获和精确 scope/身份，按真实来源日期检查年龄。不凭字段没有 Fast D1 后缀推断 Regular，不覆盖 Fast D1、外部字段或未知 cutoff。显式时间戳仍独立严格校验，政策不能覆盖未来或矛盾时点；不生成虚拟时间戳，`historical_pit_verified=false`，不证明历史 PIT。 |
| 算符类型 | 可选 `definition_basis` 是 typed `definition` 的独立同级字段；有限推导只支持 `ts_delta`、`group_rank`、`group_neutralize`。签名 AST 只能证明名称、顺序和默认字面量；类型、含义、必要参数约束必须有适用的明确来源。缺少 `ts_delta` 的 integer-window 前提仍为 unsupported，不能从参数名、普通示例或 SuperAlpha 附录补造 Regular 约束。 |
| 前提与上下文 | `Premise` 绑定 `EvidenceRef` 和精确定位：唯一 Markdown 标题中的精确引文，或唯一字段/scope 行中的严格 JSON 值；完整来源摘要、身份和来源家族必须通过核验，索引或模型自述不足以证明。Markdown 只接收有限、无歧义语法。算符 context policy `4` 校验完整有限上下文，不以截取关键词忽略额外约束；仅接受与规范算符正文、目标/endpoint、payload、header 和摘要完全一致的终端 `Raw GET Receipt` 作为重复审计载荷。未知或矛盾 receipt 不会被当作可忽略文本。 |

版本 `2` 的来源合同经提案校验、worker、编译、绑定回执与不可变成对 release 保留，并在保存/读取的资源快照边界核对版本和来源；不允许丢弃 metadata 后降级。缓存内容键覆盖来源、规则摘要、编译/schema 版本及 context policy `4`，规则或来源改变不能冒用旧键。模型执行前、缓存重放及输出发布前均需重新验证相关来源，取消/失败的相同内容任务不自动重跑。旧 runtime readers 继续拒绝不支持的 v2；新运行仅在显式启用 paired_scout 且完整冻结上下文通过验证时使用新路径，不迁移旧快照。

输入先固定有来源的字段、算符、scope 与设置。AI 从数据含义或算符用途出发，提出经济机制、适用条件、预测方向、竞争解释和可证伪实验；每个触发点最多三个机制、每机制最多两个条件分支，不要求凑满。程序只接收严格结构化方案，不直接执行 AI 随意写出的公式。

确定性编译首版只支持 Level（水平）、Change（变化）和 Relative（有来源分组的组内排名或去均值）。基准与处理版本固定共同数据绑定和回测设置，保留分组辅助角色及来源摘要；参数网格仍留给后续研究阶段。不支持的特征、VECTOR 的未声明聚合、未知预测方向及无法识别的条件明确拒绝。条件说明不等于表达式已经加入条件过滤器。

编译结果只是 `unreviewed`、`scout_only` 草案和实验附件，不自动发布、回测、审批或提交；回测结果也不能证明经济因果。M2/M3 实现与真实部署分开：下面描述接口与边界，最终测试及部署状态以 `todo.md` 为准。旧运行的冻结内容不变。

成对 Scout 按完整基准/处理组排程，先去重再计入最多 30 个及剩余预算；不在 Scout 展开窗口、Decay、中性化参数的笛卡尔积。只有表达式、设置、scope、已知测量时段均一致的既有测量才可复用，相关性缓存不是测量替代品。Discovery/Repair 保持原优化路径。

时间线区分 queued、submitted、polling、measured、failed 和 uncertain（提交结果尚不确定，需核对原请求，不能盲目重发）。两臂都有测量才标记 comparison measured；切换 source 后仅显示与当前 source 附件摘要匹配的成对计划，不用新批次的空进度重写历史实验状态。这些显示不增加操作按钮，也不授予提交权限。

### 成对实验与证据反馈

- 默认关闭。Console 的新 Start 从 `configs/workflow_defaults.example.json` 读取严格布尔 `research_policy.paired_scout`，允许本机 `configs/workflow_local.json` 覆盖，保存到准备请求后传入冻结快照；本机配置不入 Git。表单不能启用此模式，运行期间也不重新读取配置。CLI 使用既有 `--workflow-defaults` / `--workflow-local`，显式 YAML 配置中的 policy 优先。设为 false 或缺省保留原路径，不修改既有运行。

设计任务的 context 合同 `hypothesis-context-3` 要求 `context_refs.sha256` 同时匹配完整文件字节与规范化 JSON 身份；worker 启动前拒绝格式变化或损坏。旧合同任务及其失败记录保留，不覆盖成成功记录、不自动重跑。实际迁移、模型草案、单独审核、资源发布、Console 加载验证分别有证据才算部署完成；测试通过不代替实际部署。
- 审核先调用 `design_review_identity(job, policy)` 获取确切目标，再由独立审核提供 `job_key/result_digest/reviewer/reviewed_at` 给 `export_reviewed_design_proposals(...)`。它重验来源、导出实验 wrapper 和既有发布接口所需资料，不自动激活 release。算符必须预先审核；模板仍是 scout_only，候选与最终提交权限不变。
- 有研究记录后，通过既有知识维护编译生成可重建的 `machine/mechanism_evidence.json`，并在既有研究案例中写入机制、条件、对照、差值和限制；不在每次 Start 全量编译，也不另开经验目录。
- 证据按精确版本、数据角色、scope、设置和已知测量时段分开；缺对照、缺检查、矛盾记录保持 inconclusive，429/超时是 operational_failure。提交成功不证明经济假设成立，生产门槛失败也不等于假设被证伪。
- 当前 compiler 没有机器可判定的数值预测比较规则，所以真实 M1 对照保留 observed_differences 并标为证据不足；不猜 Sharpe 阈值或因果关系。只有已有明确数值比较且证据相容时，纯证据模块才可标注限定条件下支持/反对预测。
- `compile_hypothesis_design_command` 的 `mechanism_query` 指定相关历史条件，`mechanism_maximum` 为整数 0..12。仅选中记录的完整本地副本与摘要绑定到新任务，不塞入全账本、不扩大 context 上限；无关未选历史不改变冻结任务。历史只作观察提示，不能升级为官方定义或自动审批；重复已耗尽想法必须说明新的可证伪实验。

这些接口供受控维护与自动调度使用，不要求日常用户填写内部产物或多点 gate。日常仍为选择 Option Card、Start/Stop；线上资料更新、代码部署和最终 Alpha 提交是独立授权事项。

M1 的维护接口为 `prepare_hypothesis_design_job(root, evidence_pack, policy)` 和 `compile_hypothesis_design_command(root, config)`，不替换 Console 现有知识编译命令。后者显式接收 `evidence_pack`、完整编译 `resources` 和可选 `executor_argv`；缺执行器时只返回 `pending`，不会猜测模型配置。新 checkpoint 名为 `hypothesis_design`，资料和任务证据复用 `machine/semantic_jobs/`。`completed` 仅表示草案成功；`blocked`、`cancelled` 与来源/缓存诊断必须保留，不能以删除失败回执的方式自动重跑。实际实现及验收状态以 `todo.md` 为准。

准备接口只冻结提案输入；执行接口返回的 `job` 还绑定完整编译资源，可能不是同一个内容键。取消执行任务时使用执行接口返回的 job，不取消另一个准备任务。完整资源包括 `field_rows`、`operator_rows`、`source_index`、完整 `source_texts`、原始 `evidence_pack` 和全套 `settings`。这是显式维护 API，不是让用户手工复制运行产物来推进研究。

低层绑定接口仍兼容原四个位置参数：`bind_template(template, field_rows, operator_rows, scope, *, resource_contract_version=1, evidence_context=None)`；v2 必须显式传入已验证的 `source_index`/`source_texts` 上下文。共享 resolver 返回 `supported|unsupported`、值及拒绝原因，不把来源缺失改成 verified。提案不能选择可信全局版本或自行认证前提。

来源维护复用既有接口：`capture_resource_subset(..., request_limit=12)` 只抓取明确选定的官方 Learn/算符 list/detail 目标，失败 GET 也计入预算，只写 raw，不自动编译或发布；`repair_source_metadata(..., dry_run=True)` 先审计可核实的原始字节，保留旧日期/摘要及修复回执，无法验证的旧来源不能修成可信来源。索引写入使用共享锁与逐文件原子替换，不声称人读/机器索引是跨文件原子事务。

大字段 JSONL 使用 `extract_field_source_subset(..., max_rows=30)` 流式核验原始完整摘要和精确行，生成小型不可变 `verified_raw_extract`，不扩大/截断模型资料包来冒充完整输入。摘录保留原始捕获日期、原路径/完整摘要、行身份/摘要及独立抽取时间；规范 Markdown JSON adapter 只定位已验证的字段捕获，不接受普通文档示例。`_material` 在模型或缓存访问前重验摘录回执与原始实际字节，发布也重验原始来源；原件变化、重复身份、scope 或回执不一致均阻塞。摘录不是新抓取，也不刷新来源年龄或补充语义。

2026-10-14 的真实资料抽样审计未发现可执行绑定：主要缺少权威算符类型定义、字段可用时点/粒度/必要单位，以及部分来源索引或 Markdown 正文摘要的一致性。创建日期和抓取日期不能代替历史可用时点；修复未来抓取的摘要写法不会自动修复旧来源，也不会刷新资料日期。需要单独核实或补采可信资料后再编译，不能由 AI 猜齐。

开发者可用 `scripts/demo_hypothesis_design.py --mode audit|demo --evidence-pack <JSON> --output-dir <独立输出目录>` 做纯离线验证。`demo` 输入包含完整 `resources` 和原始结构化 `answer`；`audit` 输入包含 `knowledge_root`、`scope`、`template_requirements`。输出为 design、drafts、experiment、coverage、diagnostics 五份 JSON，只是机器测试材料，不是另一套 Obsidian 知识库。工具拒绝写入知识库、研究运行及源码目录，拒绝覆盖不同内容；同一输入可逐字节重放。共享策略参数也可通过 `scripts/demo-hypothesis-design.sh` 的参数设置。这是维护开发入口，不要求普通用户通过命令行启动产品。

## 模型何时介入

日常 Console 的模型任务保存在本次运行的 AI checkpoint 中。旧版研究计划消费有限的持仓衰减选择；v2 的 `hypothesis_batch_plan` 从冻结的假设版本、字段绑定和合法参数方案中选择，实际选择写入候选来源，不允许模型临时改代码、范围或预算。Repair 消费单次修改决策；选题摘要、候选说明和研究记录摘要仍是建议，不能替代检查或审批。独立知识维护使用 `semantic_compile`，只在你启动知识维护时执行，不在日常研究中全量重编。

Console 运行入口配置本机 Codex CLI 只读 worker，推理强度不超过 `medium`，输入有字节上限；模型本身不调用 WQB、回测、批准或提交 Alpha。默认及可取消的模型子进程都过滤平台和敏感环境变量，但只读沙箱不是文件读取白名单，不承诺对本机所有文件的隔离。CLI 未配置 executor 时不声称模型已执行。

Repair 新测试必须消费有效的 AI 决策：模型读取母策略、指标、已测子策略对比与启动时的本地知识快照，提出一次只改一个属性的假设，代码校验后才生成回测载荷。当前支持 decay、中性化、截断和方向；缺少权威算符签名时不开放任意算符嵌套，缺少本地 PnL 时明确标为不可用，不虚构曲线分析。其他节点的摘要仍是建议，不能代替平台检查或人工授权。

模型子任务通过非交互 `codex exec` 运行，不保证出现在当前 Codex 对话页面；查看 AI judgments 与 `stages/ai/` 输入/输出/事件，以及 `runtime/repair_decisions/`。`validated` 表示方案通过本地校验，`consumed` 表示执行器已采用该方案，不代表回测通过。模型失败会阻塞并生成维护案例，不会悄悄退回固定规则并声称 AI 已参与。Stop 会取消驱动所属模型子进程。

Repair 独立母策略按持久化预留额度调度：一个子策略等待平台时，其他可执行的独立测试可以推进；并非无限并发。重启复用原 URL 和已完成 AlphaID，旧冻结计划不会被 AI 改写。已测结果反馈到下一次模型判断，最多使用原 Repair 和研究预算。等待超过 30 分钟产生一次异常等待通知，但不会假定模拟失败或重复提交。

运行时间或步数耗尽时显示 **Runtime limit reached**，并把去重消息投递到维护窗口；投递失败或不确定也保留证据。此时 Resume 不会清空累计时间，也不能扩大权限。代码修复验收通过不代表运行额度已续期；恢复需要独立的运行授权决定。资源回执在 `runtime/boundaries/`，与代码维修审批分开。

## 碰到异常

历史任务授权核对（2026-10-11）：排程文件里的 `simulation_budget` / `api_budget` 是模板研究单元估算，不是执行端硬上限，也不是平台剩余配额。执行端依据 `runtime_control.json` 的用户意图、live 权限与 `max_simulations`，以及 `runtime_status.json` 的尝试计数。缺少持久授权的旧任务不会由驱动自动套用默认预算启动；点击 Stop 仍可暂停，但不会补授恢复权限。Console 显示 `Runtime authority required` 并禁用 Resume，维护窗口须先核对证据与原授权。

维护窗口可用 `python -m wqb.run_authority --run-dir <run>` 生成只读核对报告：分别列出规划估算、运行授权、提交事件行数、去重候选数、进度 URL 数和证据错误。URL 数不是 HTTP 请求数；重复事件行不能当成新增 Alpha。报告只覆盖绑定的 source，不宣称完整多阶段或账号额度。缺失计数、历史计数不一致时不推算可用额度，平台配额保持未知；命令不会修文件、迁移权限或恢复工作流。非空但不完整的旧授权同样需要核对；worker 状态不能补齐用户授权。完整授权须包含运行意图、布尔 live 权限、请求版本以及三个正整数上限，提交前也会重新验证。

请求优化维护增量（2026-10-11）：常规与计划恢复的批量请求统一采用保守的每批最多 5 个，30 个候选不代表一次 HTTP 提交 30 个。受控运行会在 `runtime/request_metrics.jsonl` 记录脱敏后的实际请求次数、429、等待提示与批次大小；这些是诊断数据，不是剩余配额。阻塞退出会保存 `runtime/recovery/` 案例，便于后续自动处理。代码类案例进入 `awaiting_maintenance_confirmation`；历史 `ai_diagnosis_pending` 不表示模型已执行或代码已修复。自动改码和部署仍未启用。

平台返回的 `Retry-After` 是最早允许重试的时间，不能用本地 15 分钟退避上限截短。例如平台要求等待 1 小时，就保留完整 1 小时；运行预算不足时应停止并保留队列，不提前请求。只有平台未提供等待时间时才采用有上限的本地退避。

维护通知降级（2026-10-11）：疑似代码/接口契约缺陷会生成本地维护请求，运行停在 `awaiting_maintenance_confirmation`，不自动改码。阻塞事件立即由脚本调用 `codex queue` 投递到 `runs/maintenance_channel.json` 绑定的维护聊天，不使用定时自动化、不周期性调用模型。需要本机 Codex 消息通道可用；排入队列不保证已被处理。维护窗口先诊断、给出建议，等待用户确认后才修改代码。普通平台等待、凭据/知识缺口、未知提交核对不作为代码修复通知。

Console 的 Workflow Progress 显示：`Waiting for maintenance-chat delivery` 表示尚未投递；`Maintenance-chat delivery failed` 表示发送前失败，证据仍在本地；`Delivery uncertain` 表示调用后未得到确定结果，不自动重复发送；`Request queued to Codex` 仅表示消息入队；`Maintenance chat notified` 表示维护窗口已确认收到，仍等待用户同意改码。通知/回执不授权修改研究规则、增加预算、提交 Alpha 或忽略暂停。修复后需验证并由维护窗口通知运行窗口继续；用户明确暂停时仍保持暂停。

维护窗口在用户明确同意具体修复后，使用 `python -m wqb.maintenance_resolution approve --run-dir <run> --case-id <case> --confirmation-reference <用户确认记录引用>` 保存授权。不要把脚本通知或本功能实现的授权当成某个真实故障的修复授权。此时状态为 `maintenance_approved`，运行仍不能恢复。完成修复后，用返回的 approval ID 执行 `python -m wqb.maintenance_resolution verify-and-resolve --run-dir <run> --case-id <case> --approval-id <id>`；该命令固定执行全量 unittest，失败、零测试或验证中代码变化都不能解除阻塞。验证通过保存 `runtime/maintenance_verification/<case>.json`，状态才成为 `resolved`。它不部署代码、不启动研究、不更改暂停或预算；之后由维护窗口按既有恢复流程交还运行窗口。同一问题再次出现会生成新案例，不复用旧通知回执。

因暂停或旧验证失效而重新确认维护时，使用 `approve` 返回的 **case ID 和 approval ID** 执行验证，不要沿用输入的旧 case ID。失效的已解决案例会产生关联的新案例，旧案例及其验证证据不会覆盖；暂停状态仍保留。

受控 429 恢复不再清空限流计数来假装平台已恢复：完整冷却结束、运行仍获 live 授权且恢复预算未耗尽时，驱动消耗一次既有恢复额度，为相同平台证据授予 90 秒重试窗口。窗口过期或遇到新 429 立即失效；只有平台实际成功才按原有成功路径重置计数。运行时限在冷却中耗尽时停止，不提前授予重试许可。此机制不会增加研究预算或自动提交 Alpha。

重试许可会在每次批量/单个提交前再次检查，受控 HTTP 客户端在认证完成、实际 POST 前再检查一次。许可过期时不发请求，回到受控恢复；Repair 记录为本地拒绝，不等同于平台 429 或响应丢失。批准过的代码修复若验证回执不完整、测试未真正成功或源代码已变化，仍保持阻塞。暂停/继续不会消除尚未解决的代码缺陷。

- 长时间运行但策略/事件/任务时间戳不变：查看 **Recent Jobs** 和 **Current Work**。若只有按钮重复同一状态，应交给维护任务新增复现测试并修复状态契约，不通过重复点击解决。
- `Readiness blocker`：根据证据更新精确 scope 的平台资料并 compile；不能用 seed/cache 假装测量覆盖。
- `Maintenance blocker` 或 429 预算耗尽：保留 source run 和 rate-limit state，停止 live 重试；维护任务确认原因和恢复策略。
- `uncertain simulation submission`：平台可能已接受 POST，但客户端未拿到进度 URL。系统保留 `SUBMISSION_STARTED` 证据并禁止自动重试；先通过平台记录核对身份，不能靠再次点击 Resume 猜测是否成功。
- AI judgment 为 `pending` 或 `failed`：表示没有有效模型建议，不代表研究指标失败；查看 checkpoint 事件和本机 Codex CLI 环境。
- 页面显示旧内容：先确认本地后台版本；不要用旧进程状态继续提交或重复模拟。

Console 只接受同源页面的写入请求；Start/Resume 还会校验当前动作版本。若旧标签页的按钮被拒绝，刷新页面后再根据新的 Current Work 决定，不要绕过阻断。

Resume 在后台实际写入运行意图时再次校验版本，延迟执行的旧任务不能覆盖你随后点击的 Stop。更新项目代码后需要重启已核实属于本项目的旧后台；双击入口会拒绝复用旧代码并显示诊断，不会擅自终止正在工作的进程。

项目规则要求把反复出现的问题变成代码、测试、Console 文案或知识库规则。维护任务的当前计划与交接在工作区 `todo.md`，架构在 `milestone.md`；项目操作不依赖某一个超长对话窗口。最终 Alpha 提交永远需要单独明确授权。

### Research rounds and deferred correlation checks

For a normally authorized mission, weak triage or exhausted Repair returns to a different measured knowledge-backed Scout selection, within the existing simulation and round limits. Earlier evidence is preserved in `rounds/round-NNNN/`; `research_rounds.json` records lineage, reservations and stop reasons. No extra per-round click is required. A missing legitimate next plan, unknown usage or incomplete source evidence pauses the loop rather than declaring success.

`Research loop paused` is not a completed mission. `research_mission_authority_required` means the legacy original-only permission is exhausted; Resume cannot grant a new budget. Once its frozen batch is completely checked, choose an Option Card and **Start workflow** for a new bounded mission. `research_plan_unavailable` means no different validated knowledge-backed selection is available, not that the platform rejected every possible strategy. No additional per-round clicks are needed inside an authorized mission. Weak results rotate to a new knowledge-backed Scout batch; measured signals produce an immutable Seed and actual Discovery batch, then bounded Repair. Scout/Discovery each allow 1..30 distinct valid candidates: 30 is a maximum, never a minimum. Plans are saved before multisimulation submission; partial completed queues are not kept waiting for nonexistent candidates. Restart reuses durable queues and checks, not fresh submissions of the same identities.

Zero valid novel Scout candidates cause a local same-round switch to another compatible Start-snapshot field/template, recorded durably without changing quota or discovering data online. If no alternate exists, the exact planning cause is displayed and event-routed to maintenance, not silently treated as a platform wait. Stop remains durable. Maintenance verification releases only the stale planning stop; it never starts research or authorizes Alpha submission. Explicit vector reducers in a template consume the raw VECTOR field; the generator must not add a second `vec_avg`.

Remaining simulation capacity also caps the next Scout reservation and source queue:143 used of150 permits at most7 new candidates, not a mandatory30. Explicit round ceilings still apply. Actual simulation/round limits publish deduplicated resource notices with usage/limit and delivery state, distinct from code-repair requests. Continue cannot enlarge these limits; code verification preserves real resource exhaustion. A verified obsolete full-batch stop may be released locally without resuming research or overriding Stop.

`research_batch_plan` is a consumed AI decision, unlike advisory checkpoint summaries: the read-only Codex worker chooses a decay only from the allowed set for the exact field/template, the controller validates it and the generator uses it. Input/output/receipt are under `runtime/research_plans/` and `stages/ai/`. Failed or mismatched decisions stop construction and show a blocker; they cannot grant budget, invent checks or approve candidates. Other risk/reflection checkpoints remain advisory. New template invention and benchmark changes still require the proposal/approval route. Full offline multi-round acceptance proves control flow, not live platform throughput or Alpha quality.

The checker reads Alpha detail first. Missing or failing baseline evidence does not invoke the expensive `/check` endpoint. Only passing baseline checks permit full submission checks, including SELF/PROD correlation. Deferred checks may support research-only near-miss assessment, never candidate eligibility. Final Alpha submission still requires separate explicit approval.

## Knowledge freshness policy (2026-10-12)

Repair progress waiting is automatic: the same submitted URL is polled once per
slice, then at least60seconds later (or later if the platform requests it).
`simulation_processing`/Next wake means the platform is still working, not a new
simulation or a code-repair request. Stop interrupts the wait safely; Continue
reuses the recorded identity. Once an Alpha ID is received, it is persisted before
checks, so checking recovery does not restart simulation polling. The existing
total runtime limit still applies; this does not promise platform completion.

Backtest automatically recovers checks for existing pending Alpha identities;
it does not resubmit simulations. Baseline failures still skip expensive
correlation checks. Pending responses get at most three attempts with 60-second
waits; actual 429 uses platform Retry-After and the existing threshold policy.
An exhausted or malformed check stays blocked, never qualified. Recovery progress
is persisted in `stages/backtest/check_recovery.json`, preserving identity and
artifact provenance across restarts.

Knowledge manifests use a 90-day default, configured by `wqb/knowledge_age_policy.py`.
The current vault manifest was explicitly migrated to 90 days without changing
source capture dates. Age above 90 days is stale; absent files still block.
Changing this policy does not certify factual completeness, extend activity
deadlines, renew Alpha correlation evidence or grant research permission.
Candidate evidence keeps its separate bounded validity policy. Previously blocked
Start receipts are historical evidence; a new Start performs a fresh preflight.

## Reading Repair Experiments

No additional research button is required. New Repair AI decisions name a measured
target (Sharpe/fitness higher, turnover lower), one permitted edit, economic
hypothesis, risks, falsification and applicable conditions. Existing attempt
receipts retain the baseline and measured comparison. A local `accept` means the
target improved without other measured metric regressions or new failed checks;
it never means platform-qualified or submitted. Missing scope/measurement period,
nonfinite target values and legacy decisions are `inconclusive`, not invented successes.

Use the existing knowledge-maintenance workflow after research to compile the
human-readable trajectories into `knowledge/wiki/60_research_cases/<run_id>.md`.
Raw research records and machine research records retain provenance; no duplicate
experience ledger is created. Reports are bounded summaries, not private model
reasoning, causal proof or permanent trading advice. Start does not compile wiki.
Old pending simulations and consumed decisions retain their original identities;
new operators and final Alpha submission still need separate authorization.

Repair restart also validates the complete import/Discovery/check/Repair evidence
chain before using cached same-platform collision results. The adapter and
scheduler share one cache-validation function; this reconciliation never replays
a simulation POST. Invalid import lineage or conflicting checked results require
maintenance, not repeated Resume clicks or manually copied artifacts.

### Repair AI Input

Each Alpha receives four default input sections, exactly one sentence each:
strategy, problem, previous experiments, and this round's task. Core metrics and
known failed checks/limits are shown; unavailable economics or thresholds are
explicitly unknown. Longer check lists and earlier experiments are explicitly
referenced, not discarded. Full exact expressions/settings, raw results and
history remain in immutable hashed run-local supporting evidence.

The background read-only Codex CLI worker reads supporting evidence before
deciding and may consult run_manifest.json's immutable knowledge snapshot; it
does not implicitly consume the latest mutable vault. Its activity is separate
from this maintenance chat. Medium reasoning remains enforced; the model is
inherited from CLI configuration. The character guard is not a token/billing
limit. The planner checks brief characters; the worker separately checks rendered
UTF-8 byte size without slicing. Read-only sandbox blocks writes but is not an enforced read-directory
allowlist; references in the prompt must not be advertised as one.

Existing context-overflow pauses can re-enter the repaired planner through the
same Console Resume after maintenance verification. This exception still
requires the exact known planning fault, verified append-only results, complete
import/Discovery/check/Repair lineage and checked/waiting attempts; arbitrary
faults or modified results do not become recoverable.

### Repair Output Format Recovery

The worker output schema pairs commands strictly: stop/none/0, or test with one
supported edit and its typed value. Explanation belongs in rationale fields,
not action/edit. Legacy completed outputs are recoverable only through exact
recognized formats consistent with measured settings/history, never arbitrary
prose. The original rejected receipt remains untouched; a separate
`.normalized.json` receipt records the source path, SHA256, policy and canonical
decision while retaining the original model judgment. This is a format
conversion, not a new model decision, qualification or submission approval.

Resume reuses verified local judgments rather than requesting another model call.
Scheduler checks plan integrity before adopting a stop/test and before reusing
persisted stops on restart. Tampered or ambiguous evidence stays blocked. Exact
known output-contract pauses retain the normal Console Resume path only after
maintenance verification and complete import/result lineage validation.

### Duplicate Simulations And Activity Snapshots

Repair recognizes both genuine simulation-hash schemes by recomputing them from
the exact expression and settings; unknown hashes never become automatic aliases.
Legacy cross-scheme aliases require identical settings and platform Alpha ID.
For nonqualified research only, PASS/WARNING MATCHES_COMPETITION and MATCHES_THEMES
snapshots may differ while all numeric and other check evidence agrees. Both raw
snapshots and lineage digests stay preserved; this never creates submission-ready
evidence or skips correlation checks.

Before another simulation, identical verified expression/settings are checked
across parent lineages. Compatible nonqualified results are reused with source
digests and zero new simulation reservation; conflicts block rather than replay
POST. Restart validates reused source and child evidence. Existing qualified rows
are not converted into fresh qualified repair children.

### Submitted Result Unavailable

Only a progress-poll404 with a verified original submission can be isolated as
`result_unknown`. Authentication/check404 and429 keep their own error handling.
Local original completion records take priority: recover that Alpha's checks,
never submit the expression again. Otherwise keep a source-bound
`result_unknown.json`, the original POST identity and its consumed reservation.
Unknown means neither simulation failure nor checked success; independent parents
may advance and completed Repair receipts expose `unknown_result_count`.

Restart validates the specific iteration/variant, plan and submission-journal
digests before skipping the isolated attempt. It neither polls nor authenticates
again for persisted unknown evidence. Tampering or ambiguous identity blocks
instead of silently isolating another attempt. Human research reports retain an
inconclusive trajectory. There is no automatic resubmission or quota refund.

A potential single remeasurement is a separately authorized new attempt, not
Resume/replay of the original POST; it remains disabled in routine research.
Maintenance of this case uses the existing recorded404 and local original-identity
records, not a fresh platform-success claim or broad online search.
