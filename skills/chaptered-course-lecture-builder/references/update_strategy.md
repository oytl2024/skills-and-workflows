# Update Strategy

## State file

每次运行前，先生成或刷新：

```text
.course_lecture_skill_state.json
```

命令：

```powershell
python scripts/course_state.py scan --root <课程文件夹> --state <课程文件夹>\.course_lecture_skill_state.json
```

## What the script tells you

脚本输出中最关键的字段有：

- `mode`
- `added_files`
- `changed_files`
- `removed_files`
- `affected_chapters`
- `unmapped_changed_files`
- `chapter_inventory`

## Update rules

### Initial mode

若 `mode = initial`：

- 说明没有旧状态
- 读取全部材料
- 生成全部章节
- 生成总逻辑地图

### Incremental mode

若 `mode = update`：

先按 `affected_chapters` 更新这些章节。

再处理 `unmapped_changed_files`：

- 如果是作业、题库、总复习材料、考试材料
- 且文件名没有章号
- 就必须做语义判断，把它们映射到相关章节

只有确定某章节受影响，才重写该章节文件。

## File mapping rules

### Direct mapping

文件名中带有 `第NN章`，直接映射到对应章节。

### Semantic mapping

以下材料经常不带章号，但会影响讲义：

- 作业
- 习题
- 题库
- 期中期末复习材料
- 课程总结

这些文件要按内容决定影响章节。判断依据包括：

- 明确章节标题
- 题目所对应的模型
- 已有章节讲义中的术语体系
- 源课件的章节主题

### Global files

以下内容通常被视为全局材料：

- 课程作业总包
- 总复习
- 总结笔记

如果它们变化，只更新实际被引用到的章节，不做无差别全量重写。

## Always refresh the logic map

只要有任意章节更新，就同步刷新课程级知识逻辑地图。

若反查表存在，且题目材料有更新，也要同步刷新反查表。
