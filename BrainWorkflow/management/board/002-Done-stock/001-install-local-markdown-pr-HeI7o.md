---
title: Install local Markdown project board
status: Done
signboard_id: HeI7o
signboard_board: board
signboard_list: Done
signboard_uri: signboard://open-card?id=HeI7o
createdAt: 2026-10-08T12:36:43.085Z
activity:
  - type: created
    at: 2026-10-08T12:36:43.085Z
---
Signboard 1.7.4 downloaded from official GitHub release, SHA256 verified, board stored in this repository.

2026-10-08 launcher repair: the old script opened a window without selecting the board. The packaged app treats a leading `signboard://` URL as a CLI command; the launcher now uses `--` before the deep link, registers this board as trusted in a project-local profile, and waits for Signboard to persist it as active. Fresh-profile and actual double-click screenshots show To-do, Doing, Done and six cards. See `management/README.md` and `tests/test_signboard_launcher.py`.
