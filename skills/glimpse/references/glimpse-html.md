# glimpse-html

Use this reference only after a Markdown explanation exists. The HTML should visualize the Markdown logic; it should not invent new claims or replace the Markdown as the source of truth.

## Preconditions

Before creating HTML:

1. Confirm there is a finished `.md` file or create one with `glimpse-md`.
2. Identify the top-level branches from the Markdown.
3. Identify the clickable leaf nodes from the `1.x`, `2.x`, or equivalent sections.
4. Keep all factual text consistent with the Markdown.

If the user asks for HTML but no Markdown exists, first create the Markdown and then generate HTML.

## Default HTML Pattern

For policy and research explanations, build a single local `.html` file:

- no external network dependencies;
- embedded CSS and JavaScript;
- a left-side or central root node with the topic name;
- two main branches by default:
  - `[Policy/System]是什么`;
  - `我应该怎么应对，以及市场上常见做法怎么看`;
- clickable leaf nodes for each `1.x`, `2.x`, or named subsection;
- a content view for each leaf node;
- a clear top-left "返回导图" button;
- a visual "已看" marker for clicked nodes;
- localStorage for visited state, with safe fallback if unavailable;
- a visible link back to the Markdown source file.

## Interaction Rules

The HTML should support:

- clicking a branch to expand or collapse its leaves;
- clicking a leaf to open the text page;
- returning to the tree without losing visited state;
- clearing visited state when useful;
- previous/next navigation between text pages if the document is sequential.

## Visual Design Rules

Make it feel like a study tool, not a landing page.

- Prioritize scanability and reading comfort.
- Use a restrained palette and enough contrast.
- Keep text inside buttons from overflowing on mobile.
- Avoid decorative visual noise.
- Use stable dimensions so hover and visited states do not shift the layout.
- Make tables horizontally scrollable on small screens.

## Content Rules

- Preserve source links from Markdown in each content page.
- Do not add new factual claims unless they are also added to the Markdown.
- Keep each content page focused on one node.
- Use plain-language summaries before dense tables.
- If the HTML is generated after a policy analysis, keep legal/safety boundaries visible.

## Verification Checklist

Before delivery:

- The Markdown file still exists unchanged unless the user asked to edit it.
- The HTML opens as a standalone local file.
- The root node, two main branches, and all intended leaf nodes are present.
- Clicking a leaf shows the correct text.
- The return button goes back to the tree.
- Viewed nodes are marked.
- The Markdown link works by relative path when files are in the same folder.
- There are no external scripts or CDN dependencies unless the user explicitly approved them.
