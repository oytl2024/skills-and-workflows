# glimpse-md

Use this reference when creating the Markdown logic layer for a sourced information deliverable.

## Purpose

Create a clear `.md` document that explains a policy, document set, market topic, or research question in a way the user can understand and reuse. The Markdown should be complete enough to stand alone and structured enough to become an HTML knowledge map later.

## Before Research

Start by identifying the user's real concern:

- What decision is the user trying to make?
- What privacy, cost, risk, eligibility, deadline, account, tax, or operational impact do they care about?
- Which terms are likely confusing and need concrete examples?
- Which parts need official sources and which parts are market reaction?

Do not organize the document around official section numbers unless that is the clearest way for the user. Prefer the user's practical logic.

## Default Structure

Use this structure unless the topic clearly needs something else:

```markdown
# [Topic]：是什么，以及怎么应对

资料截止日：[YYYY-MM-DD]

说明：[scope, limitations, safety/legal boundary]

## 目录

1. [政策/系统]是什么
2. 我应该怎么应对，以及市场上常见做法怎么看
3. 主要来源

## 1. [政策/系统]是什么

### 1.1 一句话说明
### 1.2 它不是什么
### 1.3 用户真正关心的影响
### 1.4 按现实对象拆解

## 2. 我应该怎么应对，以及市场上常见做法怎么看

### 2.1 最稳妥的应对方式
### 2.2 市场常见做法：合法 / 有风险 / 不合法
### 2.3 最简单的判断方法

## 3. 主要来源
```

For policy tasks, the two central parts are:

1. **Policy/system explanation**: what it is, what it does, what it does not do, what information/rights/obligations it affects.
2. **Response and market reaction**: what the user should do, what people in the market are doing, which actions are legal, risky, or not allowed.

## Writing Style

Write for comprehension first.

- Use short sections and concrete examples.
- Use "现实中就是..." when helpful.
- Replace abstractions with objects: account balance, brokerage account, dividend, insurance cash value, account statement, tax return, deadline, application form.
- Explain one idea per paragraph.
- When a professional term is unavoidable, define it immediately.

## Source Rules

- Attach sources to the specific claim or table row.
- Prefer primary sources:
  - laws and regulations;
  - official government or regulator pages;
  - OECD, standards bodies, official guidance;
  - official company or platform documents when discussing product behavior.
- Use social media and forums only for "market reaction" or "common claims people make"; then verify the legal conclusion with official sources.
- If a fact can change over time, browse and verify.
- If a source is uncertain, say so instead of making a confident claim.

## Handling Risky or Illegal Topics

If the user asks for evasion, hiding, false reporting, illegal avoidance, or specific operational bypasses:

- Do not provide a how-to path.
- Reframe into legal options, risk levels, and official boundaries.
- A useful table is:

```markdown
| 做法 | 现实中怎么理解 | 合法边界/风险 | 来源 |
| --- | --- | --- | --- |
| 合法做法 | ... | ... | ... |
| 有风险做法 | ... | ... | ... |
| 明确不能做 | ... | ... | ... |
```

## Markdown Quality Checklist

Before finishing:

- The title and table of contents match the actual structure.
- The user's real concern is answered early.
- Each important judgment has a source link nearby.
- The document distinguishes official facts from market reactions.
- The language is practical and concrete.
- Risky or illegal requests are handled as boundaries and risk explanations, not instructions.
- The file is useful as the source logic for a later HTML knowledge map.
