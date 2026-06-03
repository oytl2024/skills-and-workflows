# skills-and-workflows

个人可复用 skills 与工作流仓库。

## 目录结构

- `skills/`：可复用 Codex skills。每个技能一个独立文件夹，文件夹名与技能名保持一致。
- `workflows/`：预留给后续更长链路的工作流。目前仓库还没有独立 workflow 目录。

## Skills

| Skill | 路径 | 用途 |
| --- | --- | --- |
| `chaptered-course-lecture-builder` | `skills/chaptered-course-lecture-builder/` | 将按章节组织的课程材料整理成详细讲义、考试导向复习资料或分章教学手册；适合 PPT/PPTX、PDF、作业文件和混合课程资料，也支持新增材料后只更新受影响章节。 |
| `glimpse` | `skills/glimpse/` | 将政策、资料、市场信息整理成带来源、通俗、可复用的 Markdown；如需要 HTML，必须先完成 Markdown，再生成本地可点击知识导图。 |

## Skill 简介

### chaptered-course-lecture-builder

用于课程资料整理。重点不是简单摘要，而是把分章材料串成学生可以直接学习的讲义系统，帮助用户沿着知识链条复习，并在新增材料后增量更新相关章节。

### glimpse

用于政策、资料、市场信息的调查与交付。默认先做 `glimpse-md`，产出可放入 Obsidian 的 Markdown；如果用户需要可视化，再基于已有 Markdown 执行 `glimpse-html`，生成本地 HTML 知识导图。

规则：`glimpse-html` 必须在 `glimpse-md` 之后执行，不能跳过 Markdown 逻辑层直接做 HTML。
