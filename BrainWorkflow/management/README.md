# BrainWorkflow project board

The board's **Project architecture** card opens a separate local, read-only interactive graph at `http://127.0.0.1:8766/`. It opens on **Workflow**: select a research step to see its actual runtime stage, conditions, evidence and owning modules. Knowledge maintenance is a separate side loop; final Alpha submission is a manual boundary. Switch to **Modules** to inspect code, tests and dependencies. Legacy `?module=repair` task links still open Modules; `?view=workflow&step=scout` opens a workflow step. The graph reads workspace `milestone.md`; current work and handoffs are in workspace `todo.md`. Launching the board starts or reuses only the verified local graph service. If port 8766 belongs to another service, the launcher reports the conflict instead of opening an unrelated page.

Double-click `Open Board.cmd` to open the local Signboard board. The launcher verifies that cards exist, opens the project board, and reports an error if the desktop app does not select it. The board files are in `board/`; each card is Markdown and can be reviewed in Git. Signboard is installed at `../../../tools/signboard/app/` in this workspace.

## Daily use

- `To-do` contains upcoming project tasks; `Doing` contains current maintenance; `Done` contains verified work. This board tracks project engineering, not individual live Alpha progress.
- Click a card to read its description and edit notes. Drag a card between columns as its status changes; Signboard updates the Markdown file and its metadata.
- Use the `Card` button or `Ctrl+N` to add a task; choose its board and column. Use a column's `...` menu to add or rename a column. `Ctrl+K` switches open boards.
- Keep both the task plan and recovery handoff in root `todo.md`; architecture belongs in root `milestone.md`. A board card is only a visual index, so an engineering change still needs code, tests and updated durable records.

If the window shows `Create your first board`, close it and launch `Open Board.cmd` again. A successful launch prints the current card count, then the Signboard window shows all three columns. The launcher uses Signboard's supported open-board link and a project-local desktop profile; it does not require creating another board. The project architecture card adds one card to the original six.

The task cards are a visual index. `C:/Users/oytl/Desktop/pyproject/brain/todo.md` is the sole task plan and recovery handoff; `C:/Users/oytl/Desktop/pyproject/brain/milestone.md` owns project architecture. When a card changes state, update todo and link the code/test evidence in the card. Do not put platform credentials, research data, or run artifacts in cards.

For module ownership and runtime boundaries, see `../docs/operations/architecture-map.md`. The board is local; it does not replace the Console's live strategy progress.

Installed version: Signboard 1.7.4. Official repository: https://github.com/cdevroe/signboard . The installer is stored at `../../../tools/signboard/signboard_1.7.4_win.exe`; its SHA256 is `4833ebe1bed8cab36344de5e7dfa19d4d0dfa4a20deeecb44bbfbfc312deb8a5` and matches the official release `SHA256SUMS`.

Plane (https://github.com/makeplane/plane) is the more popular, team-scale alternative. It requires Docker for local Windows self-hosting; Docker was not installed on this machine when this board was set up.
