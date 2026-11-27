"""The app snapshot reads small runtime choices without requiring a retired vault path."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch


class LiveConsolePathsTests(unittest.TestCase):
    def test_hot_snapshot_accepts_owned_runtime_option_cards(self):
        from wqb.console_state import default_console_paths
        from wqb.console_server import _load_runtime_snapshot
        from tests.test_workflow_stage_adapters import valid_option
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            skill=root/'knowledge/skills/brain-research'
            skill.mkdir(parents=True)
            (skill/'SKILL.md').write_text('Methods',encoding='utf-8')
            decisions=root/'runs/decisions'
            decisions.mkdir(parents=True)
            (decisions/'research_option_cards.jsonl').write_text(json.dumps(valid_option(option_id='scope'))+'\n',encoding='utf-8')
            paths=default_console_paths(project_root=root)
            server=SimpleNamespace(console_runtime_lock=threading.Lock(),
                console_runtime_cache=dict(state=None,loaded_at=0),console_state_cache_lock=threading.Lock(),
                console_state_cache=dict(state={}))
            with patch('wqb.console_server.load_runtime_state',return_value={}), \
                    patch('wqb.console_server.build_timeline_rows',return_value=[]), \
                    patch('wqb.console_server.select_current_work',return_value={}):
                result=_load_runtime_snapshot(server,paths)
            self.assertEqual(result['option_cards'][0]['option_id'],'scope')
            self.assertFalse((root/'knowledge/machine').exists())


if __name__ == '__main__':
    unittest.main()
