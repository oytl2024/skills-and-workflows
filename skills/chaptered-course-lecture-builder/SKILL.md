---
name: "chaptered-course-lecture-builder"
description: "Use this skill whenever the user wants to turn a folder of chaptered course materials into detailed lecture notes, exam-oriented study guides, or chapter-by-chapter teaching handouts, especially when the sources are PPT/PPTX, PDF, homework files, or mixed course materials. Also use it whenever the user wants to update existing course lecture files after adding new materials, regenerate only affected chapters, or connect scattered knowledge points into a logic chain, knowledge map, or study path. This skill should trigger even if the user does not explicitly ask for a 'skill' and instead says things like '整理课件', '生成讲义', '按章节总结', '更新讲义', '串联知识点', or '做成能直接拿来学习的资料'."
---

# Chaptered Course Lecture Builder

把分章课程资料整理成“可以直接替代教材复习”的详细讲义，并在新增材料后只更新相关章节。

## 这项 Skill 的目标

你不是在做“摘要”或“提纲”，而是在做学生可以直接学习的讲义系统。输出结果应该让用户：

- 不必来回对照教材、PPT 和作业
- 能沿着知识链条学，而不是碎片化背点
- 知道每个知识点为什么成立、考题如何变化、模型如何传导
- 在新增资料后，只更新受影响章节，而不是整套重写

## 何时使用

遇到下面这类任务就应优先使用本 Skill：

- 用户要把课件、作业、教材、PDF、PPT、PPTX 整理成分章讲义
- 用户要求“每章一个文件”“详细讲解考点”“做成教学资料”
- 用户要求新增材料后更新已有讲义
- 用户要求把知识点串起来，生成知识逻辑链、课程逻辑地图、学习路径
- 用户希望只看讲义就能完成复习，而不是回头啃教材

## 输出物

默认输出以下文件：

- `第NN章知识点与考点.md`
- `<课程名>知识逻辑地图.md`

如果文件夹里存在作业、习题、题库或考试材料，建议额外输出：

- `<课程名>题目-知识点反查表.md`

精确结构要求见：

- `references/output_contract.md`
- `references/student_quality_bar.md`

## 更新机制

这项 Skill 采用“手动触发更新”，不做后台监听。

每次开始前，先运行：

```powershell
python scripts/course_state.py scan --root <课程文件夹> --state <课程文件夹>\.course_lecture_skill_state.json
```

这会产出一份 JSON，告诉你：

- 是首次生成还是增量更新
- 哪些源文件新增、删除或变化了
- 哪些章节被直接影响
- 哪些未带章节号的通用材料需要你再做语义判断

详细规则见 `references/update_strategy.md`。

## 工作流程

1. 确认课程根目录。
2. 运行 `scripts/course_state.py` 扫描状态。
3. 判断当前是：
   - 首次生成
   - 增量更新
4. 首次生成时：
   - 读取全部源材料
   - 识别章节集合
   - 为每章生成讲义
   - 生成课程级知识逻辑地图
5. 增量更新时：
   - 先更新脚本明确标出的受影响章节
   - 再语义检查未带章节号但发生变化的材料
   - 仅重写受影响章节
   - 总是同步刷新课程级知识逻辑地图
6. 如果存在作业、习题或题库，建立“题目 -> 知识点 -> 章节”的反查关系。

## 读材料的优先级

1. 原始课件、作业、PDF、PPT、PPTX
2. 若目录中已有 `_extract`、`ppt_dump`、`pdf_dump` 等文本转储，可优先用作加速读取
3. 已存在的章节讲义只作为“保留已有高质量内容”的参考，不是最终真理

若文本抽取不完整，不要因此退化成薄讲义。应结合：

- 文件名中的章节号
- 幻灯片标题
- 作业题型
- 相邻章节上下文
- 现有讲义中已经验证过的结构

来恢复知识结构。必要时明确说明不确定点，但不要因为抽取噪声而省略高频考法。

## 章节讲义的质量标准

每章都必须达到“教学资料”而不是“复习提纲”的标准。

### 知识点部分

知识点部分要回答：

- 这是什么
- 这个概念放在本章的什么位置
- 它和前后知识点是什么关系

### 考点部分

考点部分必须详细。不能只写“会考什么”，要写：

- 题目通常怎么设问
- 模型假设
- 数学表达
- 变量定义
- 推导起点
- 图形分析
- 传导链条
- 为什么会这样变化
- 易错点
- 标准作答模板

如果 PPT 或题目里出现曲线移动、新旧均衡比较、机制图或模型联立，就必须展开写清楚，不得省略为一句结论。

### 知识逻辑链部分

每章必须新增一个 `本章知识逻辑链` 部分，至少包括：

- 本章先修知识
- 本章内部主链条
- 本章与前后章节的连接点
- 建议学习顺序

优先使用：

- 箭头链式说明
- 扁平层级
- 必要时用 Mermaid 流程图

### 题目讲解部分

结合题目时，不要只给答案。要明确：

- 这题对应哪个知识点
- 它为什么这样考
- 解题步骤每一步在用哪个模型或规则
- 做错通常是因为什么

## 课程级知识逻辑地图

课程级总文件不是把各章标题堆在一起，而是要输出“课程主骨架”。至少包含：

- 课程总主线
- 各章先后依赖关系
- 高频跨章联系
- 模型之间的递进关系
- 从零开始的最短学习路径
- 考前速过路径

如果题目资料较完整，额外补上“题型反查入口”。

## 学生视角优化

这项 Skill 默认站在“学生不想回头翻教材”的立场工作。你的输出应该尽量具备：

- 不跳步的推导
- 定义、公式、图形、机制、题型五位一体
- 明确的学习顺序
- 常见误判与误区说明
- 题目反向索引
- 章节内主线与课程总主线

更多标准见 `references/student_quality_bar.md`。

## 增量更新的具体要求

- 新增或修改了 `第NN章` 材料，只更新对应章节和总逻辑地图
- 新增或修改了未带章节号的作业、题库、总复习材料，先做语义归类，再只更新相关章节和总逻辑地图
- 新增了一整章材料，则创建新的 `第NN章知识点与考点.md`
- 仅当逻辑地图受影响时重写它；通常只要任意章节更新，就应同步刷新
- 不要因为只新增了一道题，就全量重写五章，除非新增材料确实跨章节

## 最终交付前检查

交付前确认：

- 每章文件名一致、可排序
- 每章都包含知识点、考点、知识逻辑链、题目讲解
- 考点部分是教学版，不是结论版
- 章节之间没有明显术语冲突
- 总逻辑地图与各章内容一致
- 若做了增量更新，确实只改了受影响章节

## 参考文件

- `references/output_contract.md`
- `references/update_strategy.md`
- `references/student_quality_bar.md`
- `evals/evals.json`
