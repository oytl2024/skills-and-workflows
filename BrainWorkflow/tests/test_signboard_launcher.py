import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from wqb.signboard_launcher import prepare_signboard_state, launch_signboard, ensure_viewer, main
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class SignboardLauncherTests(unittest.TestCase):
    def test_main_starts_viewer_before_board_is_clickable(self):
        calls = []
        with patch("wqb.signboard_launcher.ensure_viewer", side_effect=lambda *_: calls.append("viewer") or "http://127.0.0.1:8766/"), patch("wqb.signboard_launcher.launch_signboard", side_effect=lambda *_: calls.append("board") or {"card_count": 1, "board_dir": "board"}), patch("builtins.print"):
            self.assertEqual(main(), 0)
        self.assertEqual(calls, ["viewer", "board"])

    def test_viewer_failure_still_opens_board(self):
        calls = []
        with patch("wqb.signboard_launcher.ensure_viewer", side_effect=RuntimeError("port unavailable")), patch("wqb.signboard_launcher.launch_signboard", side_effect=lambda *_: calls.append("board") or {"card_count": 1, "board_dir": "board"}), patch("builtins.print"):
            self.assertEqual(main(), 2)
        self.assertEqual(calls, ["board"])

    def test_architecture_card_has_fixed_local_link(self):
        board = Path(__file__).resolve().parents[1] / "management" / "board"
        cards = list(board.rglob("*.md"))
        matches = [p for p in cards if "title: Project architecture" in p.read_text(encoding="utf-8") and "http://127.0.0.1:8766/" in p.read_text(encoding="utf-8")]
        self.assertEqual(len(matches), 1)

    def test_viewer_rejects_unrelated_port_occupant(self):
        class OtherHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"not the project viewer")

            def log_message(self, *_):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), OtherHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "unrelated service"):
                ensure_viewer(Path(__file__).resolve().parents[3], port=server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_bootstrap_selects_existing_board_and_counts_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = root / "board"
            todo = board / "000-To-do-stock"
            todo.mkdir(parents=True)
            (todo / "000-task-a1b2c.md").write_text("---\ntitle: Task\n---\n", encoding="utf-8")
            state_dir = root / "desktop-state"

            result = prepare_signboard_state(board, state_dir)

            self.assertEqual(result["card_count"], 1)
            self.assertEqual(result["board_dir"], str(board.resolve()))
            self.assertTrue(state_dir.is_dir())
            self.assertEqual(json.loads((state_dir / "trusted-board-roots.json").read_text()), [str(board.resolve())])

    def test_bootstrap_rejects_empty_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "board"
            board.mkdir()
            with self.assertRaisesRegex(ValueError, "card"):
                prepare_signboard_state(board, Path(tmp) / "desktop-state")

    def test_launcher_uses_open_board_deep_link_and_isolated_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = root / "board"
            todo = board / "000-To-do-stock"
            todo.mkdir(parents=True)
            (todo / "000-task-a1b2c.md").write_text("# Task\n", encoding="utf-8")
            exe = root / "Signboard.exe"
            exe.touch()
            state_dir = root / "desktop-state"
            calls = []

            def fake_popen(argv, **kwargs):
                calls.append(argv)
                if len(calls) == 2:
                    (state_dir / "open-boards.json").write_text(json.dumps({
                        "activeBoardRoot": str(board.resolve()),
                        "openBoardRoots": [str(board.resolve())],
                    }), encoding="utf-8")

            with patch("wqb.signboard_launcher.subprocess.Popen", side_effect=fake_popen) as popen, patch("wqb.signboard_launcher.time.sleep"):
                launch_signboard(exe, board, state_dir)
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(calls[0], [str(exe.resolve())])
            argv = calls[1]
            self.assertEqual(argv[0], str(exe.resolve()))
            self.assertEqual(argv[1], "--")
            parsed = urlparse(argv[2])
            self.assertEqual((parsed.scheme, parsed.netloc), ("signboard", "open-board"))
            self.assertEqual(parse_qs(parsed.query)["path"], [str(board.resolve())])
            self.assertEqual(popen.call_args.kwargs["env"]["SIGNBOARD_USER_DATA_DIR"], str(state_dir.resolve()))

    def test_launcher_reports_if_renderer_never_opens_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = root / "board"
            todo = board / "000-To-do-stock"
            todo.mkdir(parents=True)
            (todo / "000-task-a1b2c.md").write_text("# Task\n", encoding="utf-8")
            exe = root / "Signboard.exe"
            exe.touch()
            with patch("wqb.signboard_launcher.subprocess.Popen"), patch("wqb.signboard_launcher.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "did not open"):
                    launch_signboard(exe, board, root / "state")


if __name__ == "__main__":
    unittest.main()
