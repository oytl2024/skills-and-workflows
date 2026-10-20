---
title: Document AI intervention and architecture map
status: To-do
signboard_id: bwXnt
signboard_board: board
signboard_list: To-do
signboard_uri: signboard://open-card?id=bwXnt
createdAt: 2026-10-08T12:36:55.795Z
activity:
  - type: created
    at: 2026-10-08T12:36:55.795Z
---
Wire actual model invocation at selected research checkpoints, then document which stages are deterministic and which use AI. The checkpoint executor contract in `wqb/ai_checkpoints.py` now persists input/output/status and requires explicit configuration, but no workflow stage currently invokes it automatically. Never label a pending checkpoint as completed AI work. Keep the board linked to test evidence.

Related module: http://127.0.0.1:8766/?module=ai
