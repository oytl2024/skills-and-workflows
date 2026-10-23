"""Local-only browser acceptance for Console SSE and stable controls."""
from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from tests.test_console_runtime import local_console
from tests.test_console_state import make_paths
from wqb import console_server
from wqb.desktop import find_browser


def main() -> None:
    """Input: none. Output: screenshots and JSON stdout. Check real Edge against isolated local snapshots."""
    output = Path('output/runtime-browser')
    output.mkdir(parents=True, exist_ok=True)
    state = {'active_workflow': {'exists': True, 'run_id': 'browser-fixture'},
             'strategy_progress': {'rows': [], 'counts': {}}, 'current_work': {}}
    with tempfile.TemporaryDirectory() as tmp, \
         patch.object(console_server, '_load_cached_console_state', side_effect=lambda *_: state), \
         patch.object(console_server, '_load_runtime_snapshot', side_effect=lambda *_: state), \
         patch.object(console_server, 'load_console_state', side_effect=lambda *_: state), \
         patch.object(console_server, 'run_console_action', return_value=SimpleNamespace(status='running')) as action, \
         local_console(make_paths(Path(tmp))) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(find_browser()), headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        resume = page.get_by_role('button', name='Resume workflow')
        assert resume.is_visible()
        assert page.get_by_text('Enable live source recovery').count() == 0
        state['strategy_progress'] = {'rows': [{'key': 'example', 'alpha_id': 'local-fixture',
            'status': 'running', 'failures': [], 'next_action': 'waiting for checks'}]}
        state['ai_checkpoints'] = [{'checkpoint_id': 'ai-browser', 'checkpoint_type': 'near_miss_interpretation',
                                    'reason': 'Review the near miss', 'status': 'pending'}]
        page.locator('#strategy-progress-body').get_by_text('local-fixture').wait_for(timeout=10000)
        page.get_by_text('near_miss_interpretation').wait_for(timeout=10000)
        assert resume.is_visible(), 'SSE removed the resume control'
        assert 'Live' in page.locator('#runtime-connection').inner_text()
        page.screenshot(path=str(output / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile overflow'
        page.screenshot(path=str(output / 'mobile.png'), full_page=True)
        with page.expect_navigation():
            resume.click()
        action.assert_called_once()
        form = action.call_args.args[1]
        assert form['action'] == 'workflow-auto-continue'
        assert form.get('state_hash'), 'Resume did not carry its action revision'
        assert not form.get('enable_live_api'), 'Resume escalated live permission'
        assert not errors, errors
        browser.close()
    print(json.dumps({'passed': True, 'resume_click': 'accepted_offline', 'screenshots': str(output.resolve()), 'live_api_calls': 0}))


if __name__ == '__main__':
    main()
