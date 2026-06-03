---
name: glimpse
description: Use this skill whenever the user asks Codex to research, organize, explain, or deliver information as policy notes, investigation notes, study handouts, sourced Markdown, knowledge maps, or visual HTML guides. It is especially relevant when the user asks for "整理资料", "政策解读", "信息整理", "讲义", "知识导图", "做成md", "做成html", "可视化", "Obsidian", or wants a reusable sourced explanation with practical implications. The skill has two modes: glimpse-md for the required Markdown logic layer, and glimpse-html for an optional visual HTML layer that must be generated only after a Markdown draft exists.
---

# Glimpse

Glimpse turns messy policy, market, forum, or document research into a clean explanation the user can actually use. It has two modes:

- `glimpse-md`: create the sourced Markdown explanation. This is the default and the required first layer.
- `glimpse-html`: create a visual, clickable HTML knowledge map from an existing Markdown logic layer. Do not run this before `glimpse-md`.

## Mode Selection

Use `glimpse-md` when the user asks for:

- policy or document interpretation;
- sourced research notes;
- a clear lecture/handout;
- Markdown files for later use in Obsidian;
- only a written deliverable.

Use `glimpse-html` when the user asks for:

- a visual guide, knowledge map, mind map, or clickable HTML;
- a tree from a finished Markdown explanation;
- progress/visited markers while reading;
- an interactive local HTML file.

If the user asks for HTML directly, first create or confirm the Markdown file. Explain briefly that HTML must follow the Markdown structure so the visual map does not become a shallow decoration.

## Core Workflow

1. Align the task in plain language.
   - State the user's real concern, not just the topic label.
   - Example: for CRS, the real concern was not "what is CRS" but "which account privacy fields can be seen."
   - Ask only for details that materially change the output. If the user already gave enough context, proceed.

2. Choose the mode.
   - Read `references/glimpse-md.md` for Markdown deliverables.
   - Read `references/glimpse-html.md` only after a Markdown file exists and the user wants HTML.

3. Research and explain around two main questions by default:
   - What is the policy/system?
   - How should the user respond, and how is the market reacting?

4. Use official and primary sources for factual judgments.
   - Prefer laws, regulator pages, official FAQs, standards bodies, government documents, official product docs, or primary company documents.
   - Use forums, X, Reddit, blogs, and social media only to identify common market reactions or rumors; do not treat them as legal truth.

5. Make the explanation concrete.
   - Use real-world objects: bank accounts, brokerage accounts, funds, insurance, company structures, tax forms, account statements, balances, dividends, sale proceeds, deadlines, fees, and practical risks.
   - Avoid unexplained professional terms. If a term is necessary, define it in one sentence.

6. Preserve safety and legality.
   - Do not provide instructions for tax evasion, false declarations, illegal regulatory circumvention, fraud, identity hiding, or evading reporting.
   - Do explain legal options, risk categories, official boundaries, and why risky or illegal actions are unsafe.

7. Keep project memory current.
   - If the task teaches a reusable preference or workflow, update the project's progress or notes file when appropriate.

## Deliverable Rules

- Markdown is the source of truth. HTML is a visualization of that logic.
- Every key judgment should have a source next to it, not only a source list at the end.
- Put URLs directly beside specific claims or table rows when possible.
- Prefer concise structure over long encyclopedic sections.
- Use Chinese when the user is working in Chinese unless they ask otherwise.
- Keep the Markdown useful in Obsidian: stable headings, simple tables, clear links, and no unnecessary HTML.
