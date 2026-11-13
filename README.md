# BrainWorkflow

面向 WorldQuant BRAIN 的本地自动化 Alpha 研究系统：**AI 提出经济假设与完整实验树，脚本负责可恢复的回测、分支判断、Seed 筛选与有限 Repair。**

日常使用是选择研究 Option Card，然后 **Start / Stop**。Windows 桌面应用展示各路实验树、策略进度、有效内核和优化轨迹，不要求用户逐阶段推进。

## 设计理念

- **先假设、后公式**：从数据含义、适用条件和竞争性解释构造可证伪实验，区分事实、实测特性与待验证假设。
- **AI 前置，执行确定**：每路初始规划生成整棵树，之后脚本依据结果选择分支；Repair 不临时调用模型猜方案。
- **冻结执行包**：脚本封装树、字段特性与科学资源，封装后不再依赖全局知识库的持续变化；Stop、预算、提交对账和检查有效性仍动态约束运行。
- **完成才退役**：真正完成树、Seed、Repair 和记录后，自动归档必要证据并清理可回收输入；暂停和预算等待不触发退役。
- **运行与维护正交**：研究使用本地资料；在线资料更新、规则改动和最终 Alpha 提交分别授权，聊天记录不充当运行状态。

详见 [产品功能、工作流与模块设计](BrainWorkflow/README.md) 和 [操作指南](BrainWorkflow/docs/operations/user_workflow_manual.md)。

## 仓库边界

`BrainWorkflow/` 包含 Python 产品代码、React/TypeScript 前端、测试、公开配置、脚本和设计文档。知识库处理代码属于产品；**实际知识库 raw/wiki/machine、研究记录、凭据、本地配置和构建产物不上传**。

外层本地 `brain/` 工作区仅保留一套 `AGENTS.md`、`todo.md`、`milestone.md`，分别管理规则、任务交接和架构；它们不是仓库内重复入口。已移除的 Signboard 和无关技能不属于当前产品，可从 Git 历史追溯。
