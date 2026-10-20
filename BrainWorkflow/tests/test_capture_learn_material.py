import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from scripts import capture_learn_material as capture
from wqb.knowledge_contracts import parse_markdown_front_matter


def _sample_capture() -> dict[str, object]:
    """Input: none. Output: dict. Build a small non-live Learn capture fixture."""
    return {
        "generated_at": "2026-08-09T00:00:00+00:00",
        "excluded": ["courses"],
        "operators": [
            {
                "name": "rank",
                "category": "Cross Sectional",
                "definition": "rank(x)",
                "description": "Rank a signal.",
            }
        ],
        "documentation_pages": [
            {
                "id": "consultant-submission-tests",
                "title": "Consultant Submission Tests",
                "category": "Documentation",
                "content": "Sharpe, fitness, self correlation, and production correlation checks.",
            }
        ],
        "documentation_errors": [],
        "search_results": {"operators": {"tutorialPage": {"results": []}}},
        "faqs": [{"question": "What are checks?", "answer": "Submission gates."}],
        "videos": [{"title": "Operators"}],
        "recommended_readings": [{"title": "Research workflow"}],
    }


def _sample_manifest(capture_payload: dict[str, object]) -> dict[str, object]:
    """Input: capture payload. Output: manifest dict. Build counts for raw Learn writers."""
    return {
        "generated_at": capture_payload["generated_at"],
        "excluded": capture_payload["excluded"],
        "counts": {
            key: len(value)
            for key, value in capture_payload.items()
            if isinstance(value, list)
        },
        "search_query_count": 1,
    }


def _documentation_fixture(identity: str) -> dict:
    """Input: page id str. Output: dict. Reproduce retained page/block schemas without live data or IO."""
    return dict(id=identity, title=identity, category='Operators', sequence=7023,
                lastModified='2026-08-26T18:32:46.381686+08:00', content=[
                    dict(id='text', type='TEXT', value='<p>Original page explanation.</p>'),
                    dict(id='heading', type='HEADING', value=dict(content='Examples', level='1')),
                    dict(id='table', type='TABLE', value=dict(data=[['Day', 'Price'], ['1', '100']],
                         firstColIsHeader=False, firstRowIsTableHeader=False)),
                    dict(id='image', type='IMAGE', value=dict(fileSize=32330, height=379,
                         title='diagram.png', url='https://api.worldquantbrain.com/content/images/fixture.png', width=1222)),
                    dict(id='equation', type='EQUATION', value=r'x=\frac{a}{b}'),
                    dict(id='example', type='SIMULATION_EXAMPLE', value=dict(regular='ts_zscore(x, 252)',
                         type='REGULAR', settings=dict(decay=4, delay=1, instrumentType='EQUITY',
                         language='FASTEXPR', maxTrade='OFF', nanHandling='OFF', neutralization='MARKET',
                         pasteurization='ON', region='USA', truncation=0.01, unitHandling='VERIFY', universe='TOP3000'))),
                ])


class CaptureLearnMaterialTests(unittest.TestCase):
    def test_legacy_card_with_matching_id_remains_operator_material(self):
        """Input: legacy card with id alias. Output: assertions. An id alone must not turn a card into a page."""
        payload = dict(name='ts_delta', id='ts_delta', definition='ts_delta(x, d)', description='Changes.')
        with tempfile.TemporaryDirectory() as tmp:
            target = dict(kind='operator_detail', id='ts_delta')
            result = capture.capture_resource_subset(Path(tmp), FakeLearnClient({'/operators/ts_delta': payload}),
                                                     [target], '2026-10-15T00:00:00Z')
            self.assertEqual(result['successful_targets'], [target])
            self.assertEqual(Path(result['raw_markdown_files'][0]).name, 'operators.md')

    def test_ordinary_documentation_retains_complete_structured_payload(self):
        """Input: structured page. Output: assertions. Ordinary capture retains raw facts as well as readable text."""
        payload = _documentation_fixture('types')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = capture.write_raw_documentation_pages([payload], '2026-10-15T00:00:00Z', root / 'raw', root=root)
            metadata, body = parse_markdown_front_matter(path.read_text(encoding='utf-8'))
            raw_json = body.split('## Raw Documentation Payload\n\n```json\n')[1].split('\n```', 1)[0]
            self.assertEqual(json.loads(raw_json), [payload])
            self.assertEqual(metadata['content_hash'], hashlib.sha256(body.encode()).hexdigest())

    def test_actual_documentation_shapes_are_lossless_and_not_operator_cards(self):
        """Input: isolated real-shaped HTTP200 fixtures. Output: assertions. Keep documentation facts and receipts distinct."""
        for kind, identity in (('operator_detail', 'ts_delta'), ('tutorial', 'simulation-settings'),
                               ('tutorial', 'fast-d1-documentation'), ('tutorial', 'vector-datafields')):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                endpoint = ('/operators/' if kind == 'operator_detail' else '/tutorial-pages/') + identity
                payload = _documentation_fixture(identity)
                session = FakeLearnSession(status_code=200, body=json.dumps(payload).encode())
                client = capture.WQBClient(session=session)
                client.authenticated = True
                target = dict(kind=kind, id=identity)
                generated_at = '2026-10-15T13:36:09Z'
                result = capture.capture_resource_subset(root, client, [target], generated_at, request_limit=1)
                self.assertEqual(result['errors'], [])
                self.assertEqual(result['successful_targets'], [target])
                self.assertEqual(len(session.calls), 1)
                path = Path(result['raw_markdown_files'][0])
                self.assertEqual(path.name, 'documentation_pages.md')
                metadata, body = parse_markdown_front_matter(path.read_text(encoding='utf-8'))
                self.assertEqual(metadata['material_kind'], 'documentation_page')
                self.assertEqual(metadata['source_type'], 'platform_learn_material')
                self.assertEqual(metadata['captured_at'], generated_at)
                self.assertEqual(metadata['payload_hash'], capture.stable_json_hash([payload]))
                self.assertNotIn('machine/operator_ledger.jsonl', metadata['compiled_targets'])
                receipt = json.loads(body.split('## Raw GET Receipt\n\n```json\n')[1].rsplit('\n```', 1)[0])
                self.assertEqual(receipt, dict(generated_at=generated_at, target=target,
                                             endpoint=endpoint, payload=payload, error=None))
                self.assertNotIn('- Definition:', body)
                self.assertNotIn('- Scope:', body)
                rows = [json.loads(line) for line in (root / 'machine/source_index.jsonl').read_text().splitlines()]
                self.assertEqual(rows[0]['content_hash'], hashlib.sha256(body.encode()).hexdigest())
                self.assertEqual(rows[0]['captured_at'], generated_at)

    def test_documentation_unknown_empty_error_and_malformed_blocks_rejected(self):
        """Input: invalid pages/blocks. Output: assertions. A valid text sibling cannot authorize unknown structures."""
        invalid = [[], True, {}, dict(value='text', arbitrary=True),
                   [dict(id='b', type='UNKNOWN', value='text')],
                   [dict(id='b', type='TEXT', value=True)],
                   [dict(id='b', type='HEADING', value=dict(content='Title', level=True))],
                   [dict(id='b', type='TABLE', value=dict(data=[['a'], [False]], firstColIsHeader=False,
                                                        firstRowIsTableHeader=True))],
                   [dict(id='b', type='IMAGE', value=dict(url='https://example.com/image'))],
                   [dict(id='b', type='SIMULATION_EXAMPLE', value=dict(regular='x', settings={}, type='REGULAR'))]]
        for kind in ('tutorial', 'operator_detail'):
            for content in invalid:
                with self.subTest(kind=kind, content=content), tempfile.TemporaryDirectory() as tmp:
                    payload = _documentation_fixture('ts_delta')
                    payload['content'] = content
                    if isinstance(content, list) and content:
                        payload['content'] = [dict(id='valid', type='TEXT', value='Valid sibling')] + content
                    endpoint = ('/operators/' if kind == 'operator_detail' else '/tutorial-pages/') + 'ts_delta'
                    result = capture.capture_resource_subset(Path(tmp), FakeLearnClient({endpoint: payload}),
                        [dict(kind=kind, id='ts_delta')], '2026-10-15T13:36:09Z')
                    self.assertEqual(result['successful_targets'], [])
                    self.assertEqual(len(result['errors']), 1)

    def test_operator_documentation_requires_exact_identity_title_and_no_error(self):
        """Input: altered documentation pages. Output: assertions. Never infer identity from title or forgive errors."""
        for changes in (dict(id='other'), dict(title=''), dict(title=True), dict(errors=['denied']),
                        dict(name='ts_delta', id='other')):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                payload = dict(_documentation_fixture('ts_delta'), **changes)
                result = capture.capture_resource_subset(Path(tmp), FakeLearnClient({'/operators/ts_delta': payload}),
                    [dict(kind='operator_detail', id='ts_delta')], '2026-10-15T13:36:09Z')
                self.assertEqual(result['successful_targets'], [])
                self.assertEqual(len(result['errors']), 1)

    def test_explicit_operator_detail_preserves_payload_with_one_get(self):
        """Input: fake documented detail endpoint. Output: one bounded GET and full raw payload, no inference."""
        payload = dict(name='ts_delta', definition='ts_delta(x, d)', description='Fictional detail',
                       parameters=dict(d=dict(type='INTEGER', required=True)))
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeLearnClient({'/operators/ts_delta': payload})
            target = dict(kind='operator_detail', id='ts_delta')
            result = capture.capture_resource_subset(Path(tmp), client, [target],
                '2026-10-15T00:00:00+00:00', request_limit=1)
            self.assertEqual(client.paths, ['/operators/ts_delta'])
            self.assertEqual(result['attempted_requests'], 1)
            self.assertEqual(result['successful_targets'], [target])
            text = Path(result['raw_markdown_files'][0]).read_text(encoding='utf-8')
            self.assertIn('"parameters"', text)
            self.assertIn('"INTEGER"', text)

    def test_operator_detail_identity_or_error_never_grants_success(self):
        """Input: mismatched/error detail fixtures. Output: failed raw receipts, no successful target."""
        for payload in (dict(name='other'), dict(name='ts_delta', errors=['denied']),
                        dict(detail='Forbidden'), [dict(name='ts_delta')],
                        [None, dict(name='ts_delta')], [dict(name='ts_delta'), dict(name='other')]):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                client = FakeLearnClient({'/operators/ts_delta': payload})
                result = capture.capture_resource_subset(Path(tmp), client,
                    [dict(kind='operator_detail', id='ts_delta')], '2026-10-15T00:00:00+00:00')
                self.assertEqual(result['successful_targets'], [])
                self.assertEqual(len(result['errors']), 1)

    def test_error_writer_accepts_explicit_run_local_root(self):
        """Input: isolated recovery root. Output: relative metadata without global root mutation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run-local-knowledge'
            output = root / 'raw/platform/learn/2026-10-15/recovery'
            original_root = capture.KNOWLEDGE_ROOT
            path = capture.write_raw_errors([dict(error='HTTPError', id='fixture')],
                '2026-10-15T00:00:00+00:00', output, root=root)
            metadata, _ = parse_markdown_front_matter(path.read_text(encoding='utf-8'))
            self.assertEqual(metadata['source_path'], path.relative_to(root).as_posix())
            self.assertEqual(capture.KNOWLEDGE_ROOT, original_root)

    def test_ordinary_paginated_error_envelope_survives_full_writer_chain(self):
        """Input: fake paginated error envelopes/temp root. Output: assertions. Never normalize errors into trusted rows."""
        for key in ("error", "errors", "detail"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                endpoint = "/faqs?limit=100&offset=0"
                envelope = {key: "Forbidden", "results": [{"question": "Example", "answer": "..."}]}
                client = FakeLearnClient({endpoint: envelope})
                rows = capture.fetch_paginated(client, "/faqs")
                payload = _sample_capture()
                payload["faqs"] = [row for row in rows if not capture.looks_like_course(row)]
                contexts = self._patched_roots(root)
                with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4]:
                    paths = capture.write_raw_learn_markdown(payload, _sample_manifest(payload))
                path = next(path for path in paths if path.name == "faqs.md")
                metadata, body = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
                self.assertNotEqual(metadata["source_type"], "platform_learn_material")
                self.assertIn("Forbidden", body)
                self.assertEqual(rows[-1]["response_payload"], envelope)
                self.assertEqual(rows[-1]["endpoint"], endpoint)
                self.assertEqual(client.paths, [endpoint])
                indexed = [json.loads(line) for line in (root / "machine/source_index.jsonl").read_text().splitlines()]
                row = next(row for row in indexed if row["path"].endswith("/faqs.md"))
                self.assertNotEqual(row["source_type"], "platform_learn_material")

    def test_paginated_later_error_preserves_prior_rows_and_stops(self):
        """Input: valid first page/error second page. Output: assertions. Preserve partial data and the blocker without more GETs."""
        first = {"question": "Example", "answer": "..."}
        envelope = {"error": "Forbidden", "results": [first]}
        client = FakeLearnClient({"/faqs?limit=1&offset=0": {"results": [first]},
                                  "/faqs?limit=1&offset=1": envelope,
                                  "/faqs?limit=1&offset=2": {"results": []}})
        with patch.object(capture, "PAGE_LIMIT", 1):
            rows = capture.fetch_paginated(client, "/faqs")
        self.assertEqual(rows[0], first)
        self.assertEqual(rows[-1]["response_payload"], envelope)
        self.assertEqual(client.paths, ["/faqs?limit=1&offset=0", "/faqs?limit=1&offset=1"])

    def test_linked_output_parents_rejected_before_dispatch(self):
        """Input: temp junction/symlink parents. Output: assertions. Never dispatch or write through links."""
        for relative in ("raw", "raw/platform/learn/2026-10-15",
                         "raw/platform/learn/2026-10-15/existing-subset", "machine"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "knowledge"
                outside = Path(tmp) / "outside"
                outside.mkdir()
                linked = root / relative
                linked.parent.mkdir(parents=True)
                if os.name == "nt":
                    completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                                               capture_output=True, text=True)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                else:
                    linked.symlink_to(outside, target_is_directory=True)
                try:
                    client = FakeLearnClient({"/operators": _sample_capture()["operators"]})
                    with self.assertRaises(ValueError):
                        capture.capture_resource_subset(root, client, [{"kind": "operators"}],
                                                        "2026-10-15T00:00:00+00:00")
                    self.assertEqual(client.paths, [])
                    self.assertEqual(list(outside.iterdir()), [])
                finally:
                    if os.name == "nt":
                        linked.rmdir()
                    else:
                        linked.unlink()

    def test_ordinary_writer_refuses_output_outside_explicit_root(self):
        """Input: temp output outside root Path. Output: assertions. Check containment before writer mkdir."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            outside = Path(tmp) / "outside"
            with self.assertRaises(ValueError):
                capture.write_raw_operators(_sample_capture()["operators"], "2026-10-15T00:00:00Z",
                                            outside, root=root)
            self.assertFalse(outside.exists())

    def test_write_rechecks_linked_parent_after_dispatch(self):
        """Input: fake GET replacing raw with a link. Output: assertions. A preflight cannot authorize later unsafe writes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            linked = root / "raw"
            client = FakeLearnClient({"/operators": _sample_capture()["operators"]})
            def replacing_get(path: str):
                """Input: endpoint str. Output: fake JSON. Replace a parent after preflight without network IO."""
                if os.name == "nt":
                    completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                                               capture_output=True, text=True)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                else:
                    linked.symlink_to(outside, target_is_directory=True)
                client.paths.append(path)
                return _sample_capture()["operators"]
            try:
                with patch.object(client, "get_json", side_effect=replacing_get):
                    with self.assertRaises(ValueError):
                        capture.capture_resource_subset(root, client, [{"kind": "operators"}],
                                                        "2026-10-15T00:00:00Z")
                self.assertEqual(client.paths, ["/operators"])
                self.assertEqual(list(outside.iterdir()), [])
            finally:
                if linked.exists():
                    if os.name == "nt":
                        linked.rmdir()
                    else:
                        linked.unlink()

    def test_ordinary_error_pages_and_rows_never_receive_material_trust(self):
        """Input: error-shaped ordinary captures. Output: assertions. Preserve errors without trusted classification."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = [{"id": "types", "content": "Forbidden", "detail": "Not authorized"}]
            paths = [capture.write_raw_documentation_pages(pages, "2026-10-15T00:00:00Z", root / "raw", root=root),
                     capture.write_raw_operators([{"name": "rank", "error": "Forbidden"}],
                                                 "2026-10-15T00:00:00Z", root / "raw", root=root),
                     capture.write_raw_rows("FAQs", "/faqs", [{"error": "Forbidden"}],
                                            "2026-10-15T00:00:00Z", root / "raw", "faqs.md", [], root=root)]
            for path in paths:
                metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
                self.assertNotEqual(metadata["source_type"], "platform_learn_material")
            self.assertIn("Not authorized", paths[0].read_text(encoding="utf-8"))
            self.assertIn('"error": "Forbidden"', paths[1].read_text(encoding="utf-8"))

    def test_subset_rejects_boolean_content_and_error_envelope_with_results(self):
        """Input: malformed successful HTTP bodies. Output: assertions. Truthiness/results do not establish material."""
        for target, endpoint, payload in (
            ({"kind": "tutorial", "id": "types"}, "/tutorial-pages/types", {"id": "types", "content": True}),
            ({"kind": "operators"}, "/operators", {"error": "Forbidden", "results": _sample_capture()["operators"]}),
            ({"kind": "operators"}, "/operators", {"detail": "Forbidden", "results": _sample_capture()["operators"]}),
        ):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                result = capture.capture_resource_subset(Path(tmp), FakeLearnClient({endpoint: payload}),
                                                         [target], "2026-10-15T00:00:00Z")
                self.assertEqual(result["successful_targets"], [])
                self.assertEqual(len(result["errors"]), 1)

    def test_http_429_body_preserved_before_raise_with_bounded_payload(self):
        """Input: fake real-client HTTP errors. Output: assertions. Retain bounded bodies and retry headers."""
        for body in (b'{"detail":"quota exhausted","code":"THROTTLED"}', b"x" * 100000):
            with self.subTest(size=len(body)), tempfile.TemporaryDirectory() as tmp:
                session = FakeLearnSession(body=body)
                client = capture.WQBClient(session=session)
                client.authenticated = True
                result = capture.capture_resource_subset(Path(tmp), client, [{"kind": "operators"}],
                                                         "2026-10-15T00:00:00Z")
                failure = result["errors"][0]
                self.assertEqual(failure["status_code"], 429)
                self.assertEqual(failure["retry_after"], "90")
                self.assertIsNotNone(failure["response_payload"])
                if len(body) < 1000:
                    self.assertEqual(failure["response_payload"], {"detail": "quota exhausted", "code": "THROTTLED"})
                else:
                    self.assertTrue(failure["response_payload"]["truncated"])
                    self.assertLess(len(json.dumps(failure["response_payload"])), 70000)
                self.assertEqual(len(session.calls), 1)

    def test_targeted_capture_writes_raw_only(self):
        """Input: fake GETs/temp Path. Output: assertions. Capture explicit sources without global mutation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = capture.KNOWLEDGE_ROOT
            client = FakeLearnClient({
                "/operators": _sample_capture()["operators"],
                "/tutorial-pages/types": {"id": "types", "title": "Types", "content": "Matrix inputs."},
            })
            result = capture.capture_resource_subset(root, client, [
                {"kind": "operator", "id": "rank"}, {"kind": "tutorial", "id": "types"},
            ], "2026-10-15T00:00:00+00:00")
            self.assertEqual(result["attempted_requests"], 2)
            self.assertEqual(result["errors"], [])
            self.assertEqual(client.paths, ["/operators", "/tutorial-pages/types"])
            self.assertEqual(capture.KNOWLEDGE_ROOT, original)
            rows = [json.loads(line) for line in (root / "machine/source_index.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["source_type"], "platform_learn_material")
                self.assertEqual(row["source_family"], "raw/platform/learn")
                metadata, body = parse_markdown_front_matter((root / row["path"]).read_text(encoding="utf-8"))
                self.assertEqual(metadata["content_hash"], hashlib.sha256(body.encode()).hexdigest())
            self.assertFalse((root / "wiki").exists())
            self.assertLessEqual({p.name for p in (root / "machine").iterdir()},
                                 {"source_index.jsonl", "source_index_write.guard"})

    def test_subset_default_budget_is_twelve_attempts(self):
        """Input: thirteen explicit fake targets. Output: assertions. Bound even successful default captures."""
        with tempfile.TemporaryDirectory() as tmp:
            targets = [{"kind": "tutorial", "id": f"page-{i}"} for i in range(13)]
            client = FakeLearnClient({f"/tutorial-pages/page-{i}":
                                     {"id": f"page-{i}", "content": "Types."} for i in range(13)})
            result = capture.capture_resource_subset(Path(tmp), client, targets, "2026-10-15T00:00:00+00:00")
            self.assertEqual(result["attempted_requests"], 12)
            self.assertEqual(result["remaining_targets"], [targets[-1]])

    def test_subset_different_capture_times_never_overwrite_prior_source(self):
        """Input: identical payload at two timestamps. Output: assertions. Preserve both capture identities."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = FakeLearnClient({"/operators": _sample_capture()["operators"]})
            first = capture.capture_resource_subset(root, client, [{"kind": "operators"}],
                                                    "2026-10-15T00:00:00+00:00")
            old_path = Path(first["raw_markdown_files"][0])
            old_bytes = old_path.read_bytes()
            second = capture.capture_resource_subset(root, client, [{"kind": "operators"}],
                                                     "2026-10-15T01:00:00+00:00")
            self.assertNotEqual(first["raw_markdown_files"], second["raw_markdown_files"])
            self.assertEqual(old_path.read_bytes(), old_bytes)

    def test_wqb_transport_requires_auth_and_never_retries_or_redirects(self):
        """Input: fake WQB session with 429. Output: assertions. Count actual HTTP attempts, not retry wrappers."""
        session = FakeLearnSession()
        client = capture.WQBClient(session=session, max_retries=4)
        with tempfile.TemporaryDirectory() as tmp:
            target = [{"kind": "operators"}]
            with self.assertRaisesRegex(ValueError, "authenticate"):
                capture.capture_resource_subset(Path(tmp), client, target, "2026-10-15T00:00:00+00:00")
            self.assertEqual(session.calls, [])
            client.authenticated = True
            result = capture.capture_resource_subset(Path(tmp), client, target, "2026-10-15T00:00:00+00:00")
            self.assertEqual(result["attempted_requests"], 1)
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(session.calls[0][0], "GET")
            self.assertFalse(session.calls[0][2]["allow_redirects"])
            self.assertEqual(result["errors"][0]["status_code"], 429)
            self.assertTrue(client.authenticated)
            self.assertEqual(client.max_retries, 4)

    def test_wqb_redirect_is_untrusted_and_keeps_http_status(self):
        """Input: fake redirect response. Output: assertions. Do not follow or lose rejected status evidence."""
        session = FakeLearnSession(status_code=302)
        client = capture.WQBClient(session=session)
        client.authenticated = True
        with tempfile.TemporaryDirectory() as tmp:
            result = capture.capture_resource_subset(Path(tmp), client, [{"kind": "operators"}],
                                                     "2026-10-15T00:00:00+00:00")
            self.assertEqual(result["successful_targets"], [])
            self.assertEqual(result["errors"][0]["status_code"], 302)
            self.assertEqual(len(session.calls), 1)

    def test_capture_budget_and_failed_request_evidence(self):
        """Input: failed fake GETs. Output: assertions. Errors charge budget and retain rate-limit evidence."""
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = "90"
        error = requests.HTTPError("rate limited", response=response)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = FakeLearnClient({"/operators": error, "/tutorial-pages/types": TimeoutError("timeout")})
            result = capture.capture_resource_subset(root, client, [
                {"kind": "operators"}, {"kind": "tutorial", "id": "types"},
                {"kind": "tutorial", "id": "unattempted"},
            ], "2026-10-15T00:00:00+00:00", request_limit=2)
            self.assertEqual(result["attempted_requests"], 2)
            self.assertEqual(len(client.paths), 2)
            self.assertEqual(result["remaining_targets"], [{"kind": "tutorial", "id": "unattempted"}])
            self.assertEqual(result["errors"][0]["status_code"], 429)
            self.assertEqual(result["errors"][0]["retry_after"], "90")
            rows = [json.loads(line) for line in (root / "machine/source_index.jsonl").read_text().splitlines()]
            self.assertTrue(rows)
            self.assertTrue(all(row["source_type"] != "platform_learn_material" for row in rows))
            text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("raw/platform/learn/**/*.md"))
            self.assertIn('"status_code": 429', text)

    def test_subset_rejects_unsafe_targets_before_any_get(self):
        """Input: invalid schemas/limits. Output: assertions. Never dispatch arbitrary paths or partial plans."""
        for invalid in ({"kind": "url", "url": "https://example.com"},
                        {"kind": "tutorial", "id": "../simulations"},
                        {"kind": "tutorial", "id": "x?query=all"},
                        {"kind": "operators", "url": "/simulations"}):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                client = FakeLearnClient({})
                with self.assertRaises(ValueError):
                    capture.capture_resource_subset(Path(tmp), client, [{"kind": "operators"}, invalid],
                                                    "2026-10-15T00:00:00+00:00")
                self.assertEqual(client.paths, [])
        for limit in (-1, True, 1.5):
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                capture.capture_resource_subset(Path(tmp), FakeLearnClient({}), [],
                                                "2026-10-15T00:00:00+00:00", request_limit=limit)

    def test_subset_zero_budget_and_invalid_payload_are_not_authoritative(self):
        """Input: zero budget/error envelope. Output: assertions. Do not grant success to absent material."""
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeLearnClient({"/operators": {"detail": "Forbidden"}})
            target = {"kind": "operators"}
            result = capture.capture_resource_subset(Path(tmp), client, [target],
                                                    "2026-10-15T00:00:00+00:00", request_limit=0)
            self.assertEqual(result["remaining_targets"], [target])
            self.assertEqual(client.paths, [])
            result = capture.capture_resource_subset(Path(tmp), client, [target], "2026-10-15T00:00:00+00:00")
            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual(result["successful_targets"], [])

    def test_ordinary_known_endpoint_writers_classify_material_only(self):
        """Input: legacy writer fixture. Output: assertions. Fix future ordinary captures without trusting errors."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contexts = self._patched_roots(root)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4]:
                paths = capture.write_raw_learn_markdown(_sample_capture(), _sample_manifest(_sample_capture()))
            for path in paths:
                metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
                trusted = path.name in {"operators.md", "documentation_pages.md", "faqs.md", "videos.md", "recommended_readings.md"}
                self.assertEqual(metadata["source_type"] == "platform_learn_material", trusted)

    def test_raw_body_hash_is_consumable_and_payload_hash_is_separate(self):
        """Input: temporary fake capture. Output: assertions. Bind rendered Markdown and preserve distinct JSON evidence."""
        from wqb.semantic_compilation import _material
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'knowledge'
            payload = _sample_capture()
            contexts = self._patched_roots(root)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4]:
                paths = capture.write_raw_learn_markdown(payload, _sample_manifest(payload))
            rows = [json.loads(line) for line in (root / 'machine/source_index.jsonl').read_text(encoding='utf-8').splitlines()]
            for row in rows:
                text = (root / row['path']).read_text(encoding='utf-8')
                metadata, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
                self.assertEqual(row['content_hash'], hashlib.sha256(body.encode('utf-8')).hexdigest())
                self.assertEqual(metadata['content_hash'], row['content_hash'])
                _material(root, row)
            operator_path = next(path for path in paths if path.name == 'operators.md')
            metadata, _ = parse_markdown_front_matter(operator_path.read_text(encoding='utf-8'))
            self.assertEqual(metadata['payload_hash'], capture.stable_json_hash(payload['operators']))
            self.assertNotEqual(metadata['payload_hash'], metadata['content_hash'])
            row = next(row for row in rows if row['path'].endswith('/operators.md'))
            operator_path.write_text(operator_path.read_text(encoding='utf-8') + 'Tampered body\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'content_hash mismatch'):
                _material(root, row)

    def _patched_roots(self, root: Path):
        """Input: temp root. Output: patch context manager. Route capture outputs to temp vault."""
        original_root = capture.KNOWLEDGE_ROOT
        learn_relative = capture.WIKI_LEARN_PAGE.relative_to(original_root)
        operator_relative = capture.WIKI_OPERATOR_PAGE.relative_to(original_root)
        return (
            patch.object(capture, "KNOWLEDGE_ROOT", root),
            patch.object(capture, "RAW_LEARN_ROOT", root / "raw" / "platform" / "learn"),
            patch.object(capture, "JSON_CACHE_ROOT", root / "machine" / "cache" / "learn"),
            patch.object(capture, "WIKI_LEARN_PAGE", root / learn_relative),
            patch.object(capture, "WIKI_OPERATOR_PAGE", root / operator_relative),
        )

    def test_learn_capture_preview_paths_avoid_legacy_wiki_directories(self):
        root = capture.KNOWLEDGE_ROOT

        self.assertEqual(
            capture.WIKI_LEARN_PAGE.relative_to(root).as_posix(),
            "machine/previews/learn_material_index.md",
        )
        self.assertEqual(
            capture.WIKI_OPERATOR_PAGE.relative_to(root).as_posix(),
            "machine/previews/operator_catalog_official.md",
        )

    def test_raw_learn_markdown_has_contract_metadata_and_source_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture_payload = _sample_capture()
            manifest = _sample_manifest(capture_payload)
            contexts = self._patched_roots(root)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4]:
                paths = capture.write_raw_learn_markdown(capture_payload, manifest)

            index_path = root / "raw" / "source_index.md"
            machine_index = root / "machine" / "source_index.jsonl"
            first_metadata, _ = parse_markdown_front_matter(paths[0].read_text(encoding="utf-8"))
            indexed_rows = [
                json.loads(line)
                for line in machine_index.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            combined_text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
            index_exists = index_path.exists()

        self.assertEqual(first_metadata["source_family"], "raw/platform/learn")
        self.assertEqual(first_metadata["source_path"], "raw/platform/learn/2026-08-09/index.md")
        self.assertEqual(first_metadata["record_count"], 1)
        self.assertTrue(first_metadata["update_check"])
        self.assertTrue(index_exists)
        self.assertEqual({row["path"] for row in indexed_rows}, {path.relative_to(root).as_posix() for path in paths})
        self.assertNotIn("wiki/10_foundations", combined_text)
        self.assertNotIn("wiki/20_semantics", combined_text)
        self.assertNotIn("wiki/30_templates", combined_text)

    def test_learn_capture_preview_writers_do_not_create_obsolete_wiki_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture_payload = _sample_capture()
            contexts = self._patched_roots(root)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4]:
                capture.write_learn_wiki(capture_payload)
                capture.write_operator_wiki(capture_payload["operators"], "2026-08-09T00:00:00+00:00")

            learn_preview = root / "machine" / "previews" / "learn_material_index.md"
            operator_preview = root / "machine" / "previews" / "operator_catalog_official.md"
            learn_preview_exists = learn_preview.exists()
            operator_preview_exists = operator_preview.exists()
            old_learn_exists = (root / "wiki" / "10_foundations").exists()
            old_operator_exists = (root / "wiki" / "20_semantics").exists()

        self.assertTrue(learn_preview_exists)
        self.assertTrue(operator_preview_exists)
        self.assertFalse(old_learn_exists)
        self.assertFalse(old_operator_exists)


class FakeLearnClient:
    def __init__(self, responses: dict):
        """Input: endpoint->payload/exception dict. Output: None. Create a single-attempt offline client."""
        self.responses = responses
        self.paths = []

    def get_json(self, path: str):
        """Input: endpoint str. Output: JSON object. Record one attempt and return/raise its fixture."""
        self.paths.append(path)
        payload = self.responses[path]
        if isinstance(payload, Exception):
            raise payload
        return payload


class FakeLearnSession:
    def __init__(self, status_code: int = 429, body: bytes = b""):
        """Input: HTTP status int. Output: None. Build an offline requests-session boundary."""
        self.headers = {}
        self.calls = []
        self.status_code = status_code
        self.body = body

    def request(self, method: str, url: str, **kwargs):
        """Input: request fields. Output: fake Response. Return rate limiting without network access."""
        self.calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = self.status_code
        response._content = self.body
        response.url = url
        response.headers["Retry-After"] = "90"
        return response


if __name__ == "__main__":
    unittest.main()
