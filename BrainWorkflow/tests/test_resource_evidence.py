"""Offline wire and source-premise boundaries, without platform or vault IO."""

import copy
import hashlib
import importlib
import json
import unittest

from wqb.knowledge_contracts import render_front_matter


SCOPE = dict(instrument_type="EQUITY", region="USA", delay=1, universe="TOP3000")
DELTA_PAGE_MEANING = 'The ts_delta(x, d) operator computes the difference between the current value of x and its value d periods ago.'
PARENTHESIZED_WINDOW_CONSTRAINTS = (
    'd >= (100).', '(d) < 10.', '<p>d &gt;= (100).</p>',
    '((d)) >= ((100)).', '((100)) <= ((d)).', '(d) \u2264 (10).', '(100) \u2265 (d).',
    r'\( d \geq (100) \)', r'\left(100\right) \leq \left(d\right)', r'\[ (d) \in [100,2520] \]',
)
UNRECOGNIZED_PARAMETER_CLAUSES = (
    r'd\geqslant100', r'd\leqslant10', 'd\u2267100', 'd\u226610',
    r'd\unknownrestriction100', r'\unknownrestriction{d}', r'd_{i}\unlistednotation100',
    r'\mathrm{d}\unlistednotation100', '\U0001d451\u2267100',
    '\U0001d451_{i}\\unlistednotation100', 'd\u2081 is documented here.',
    'd is documented here without a recognized restriction marker.',
    'Window >= (100).', 'window \u2208 \u211d.', 'The window is restricted to prime values.',
    'The windows are restricted to prime values.', 'lookback \u2208 \u211d.',
    'The lookbacks are restricted to prime values.', 'The look-back is restricted to prime values.',
    '\uff57\uff49\uff4e\uff44\uff4f\uff57 \u2208 \u211d.',
)


def documentation_fixture(page, *, kind='tutorial', duplicate=True):
    """Input: page dict/kind str/duplicate bool. Output: ref/index/texts. Build lossless writer-shaped offline evidence."""
    from scripts.capture_learn_material import markdown_record_value
    from wqb.resource_evidence import _capture_digest
    generated = '2026-10-15T13:48:14+00:00'
    endpoint = ('/operators/' if kind == 'operator_detail' else '/tutorial-pages/') + page['id']
    receipt = dict(generated_at=generated, target=dict(kind=kind, id=page['id']),
                   endpoint=endpoint, payload=page, error=None)
    path = 'raw/platform/learn/2026-10-15/subset-' + _capture_digest(receipt) + '/documentation_pages.md'
    body = (f"\n# Documentation Pages\n\nRecord count: 1\n\n## {page['title']}\n\n"
            f"- Page id: `{page['id']}`\n- Category: {page['category']}\n\n"
            + markdown_record_value(page['content']) + '\n\n')
    if duplicate:
        body += '\n## Raw Documentation Payload\n\n```json\n' + json.dumps([page], ensure_ascii=False, indent=2, sort_keys=True) + '\n```\n'
    body += '\n## Raw GET Receipt\n\n```json\n' + json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + '\n```\n'
    row = dict(path=path, source_path=path, source_type='platform_learn_material', source_family='raw/platform/learn',
        captured_at=generated, capture_tool='scripts/capture_learn_material.py', content_status='raw_markdown',
        record_count=1, content_hash=hashlib.sha256(body.encode()).hexdigest(), payload_hash=_capture_digest([page]),
        update_check='compare record count, content hash, and platform endpoint against the previous Learn capture',
        compiled_targets=['wiki/00_start_here.md', 'wiki/10_factor_principles.md', 'wiki/20_data_semantics.md',
                          'wiki/30_template_and_operator_patterns.md', 'wiki/40_benchmark_and_repair_rules.md'])
    if duplicate:
        row['material_kind'] = 'documentation_page'
    text = render_front_matter(row) + body
    row['file_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    ref = dict(source_path=path, sha256=row['content_hash'], capture_date='2026-10-15', kind='documented', experiment_refs=[])
    return ref, {path: row}, {path: text}


def page_operator_fixture():
    """Input: none. Output: record/index/texts dicts. Use actual operation prose, not a fabricated operator card."""
    from wqb.resource_evidence import MATRIX_FACTS, _digest
    page = dict(id='ts_delta', title='ts_delta', category='Operators', sequence=7023,
        lastModified='2026-08-26T06:32:46.381686-04:00', content=[
            dict(id='operation', type='TEXT', value='<p>' + DELTA_PAGE_MEANING + '</p>'),
            dict(id='table', type='TABLE', value=dict(data=[['Day', 'Price'], ['2024-06-03', '105']],
                firstColIsHeader=False, firstRowIsTableHeader=False))])
    ref, index, texts = documentation_fixture(page, kind='operator_detail')
    vector = dict(id='vector-datafields', title='Vector Data Fields \U0001f949', category='Data', sequence=30, duration='PT4M',
        lastModified='2026-09-18T13:07:17.613362+08:00', content=[
            dict(id='summary', type='TEXT', value='<style>.summary {color:red}</style><p>\u2728 Summary This article explains vector data fields and why some datasets must preserve multiple daily observations instead of reducing everything to one value too early. It shows how vec_ operators convert event-level information into usable Alpha inputs, and why these signals often require careful smoothing or decay.</p>'),
            dict(id='core', type='TEXT', value='<p>' + ' '.join(MATRIX_FACTS) + '</p>'),
            dict(id='image', type='IMAGE', value=dict(fileSize=66541, height=480, width=1181,
                title='vector desc.png', url='https://api.worldquantbrain.com/content/images/9Sm7kRCELQv-CNQI9qqQd8Fb3G8=/160/original/vector_desc.png'))])
    type_ref, other_index, other_texts = documentation_fixture(vector)
    index.update(other_index)
    texts.update(other_texts)
    definition = dict(description=DELTA_PAGE_MEANING, input_types=['MATRIX'], output_type='MATRIX',
        parameters=[dict(name='x', type='MATRIX', required=True), dict(name='d', type='INTEGER', required=True)],
        evidence_refs=[ref, type_ref])
    record = dict(operator='ts_delta', definition=definition, definition_basis=dict(operator='ts_delta',
        rule_id='ts_delta_project_window', rule_version=2, definition_digest=_digest(definition),
        signature_premise=dict(evidence_ref=ref, locator=dict(kind='markdown_quote', heading='ts_delta', quote=DELTA_PAGE_MEANING)),
        type_premises=[dict(evidence_ref=type_ref, locator=dict(kind='markdown_quote',
            heading=vector['title'], quote=MATRIX_FACTS[0]))]))
    return record, index, texts


def page_timing_fixture():
    """Input: none. Output: timing/field/scope/index/texts. Combine actual named TEXT/TABLE facts in complete offline page receipts."""
    from wqb.resource_evidence import REGULAR_DELAY_POLICY
    fixture = named_comparison_fixture()
    settings = dict(id='simulation-settings', title='How to choose the Simulation Settings', category='Getting Started',
        duration='PT6M', sequence=25, lastModified='2026-09-18T01:05:17.445496-04:00',
        content=[dict(id='policy', type='TEXT', value='<p>' + REGULAR_DELAY_POLICY + '</p>')])
    fast = dict(id='fast-d1-documentation', title='Fast D1 Documentation', category='Advanced Topics',
        duration='PT4M', sequence=1222, lastModified='2026-09-18T01:11:18.469684-04:00', content=[
            dict(id='naming', type='TEXT', value=fixture[0]['premises'][1]['locator']['quote']),
            dict(id='cutoff', type='TABLE', value=dict(data=[['Delay', 'Field Type', 'Data Timestamp', 'Information Captured'],
                ['1', 'snt_buzz', "Yesterday's market close", 'Yesterday\u2019s End-of-day data only'],
                ['Fast D1', 'snt_buzz_fast_d1', "Today's market open", 'Overnight news, events, pre-market moves']],
                firstColIsHeader=False, firstRowIsTableHeader=True))])
    for page, positions in ((settings, [0]), (fast, [1, 2])):
        ref, index, texts = documentation_fixture(page)
        fixture[3].update(index)
        fixture[4].update(texts)
        for position in positions:
            fixture[0]['premises'][position]['evidence_ref'] = copy.deepcopy(ref)
    fixture[2]['as_of'] = '2026-10-16T00:00:00Z'
    return fixture


class DocumentationPageTests(unittest.TestCase):
    def test_unrecognized_parameter_notation_is_unsupported_without_math_parsing(self):
        """Input: canonically rehashed unknown d clauses. Output: None. Reject any unrecognized parameter notation on operator/type pages."""
        from wqb.resource_evidence import resolve_operator_definition, validated_documentation_page
        for position in (0, 1):
            for clause in UNRECOGNIZED_PARAMETER_CLAUSES:
                for kind in ('TEXT', 'TABLE'):
                    fixture = page_operator_fixture()
                    premise = [fixture[0]['definition_basis']['signature_premise'],
                               *fixture[0]['definition_basis']['type_premises']][position]
                    page = validated_documentation_page(premise['evidence_ref'], fixture[1], fixture[2])
                    value = clause if kind == 'TEXT' else dict(data=[['Expression'], [clause]],
                        firstColIsHeader=False, firstRowIsTableHeader=True)
                    page['content'].append(dict(id='unknown-parameter', type=kind, value=value))
                    self.replace_page(fixture, page, position)
                    ref = premise['evidence_ref']
                    validated_documentation_page(ref, fixture[1], fixture[2])
                    with self.subTest(position=position, kind=kind, clause=clause):
                        result = resolve_operator_definition(*fixture, resource_contract_version=2)
                        self.assertEqual(result['status'], 'unsupported', result['rejections'])

    def test_known_operation_prose_and_illustrations_remain_exempt(self):
        """Input: finite audited operation prose/illustration. Output: None. Keep illustration as context, not integer-domain or arithmetic proof."""
        from wqb.resource_evidence import resolve_operator_definition, validated_documentation_page, DELTA_PAGE_INTRO, DELTA_PAGE_ILLUSTRATION
        fixture = page_operator_fixture()
        ref = fixture[0]['definition_basis']['signature_premise']['evidence_ref']
        page = validated_documentation_page(ref, fixture[1], fixture[2])
        page['content'][0]['value'] = '<p>' + DELTA_PAGE_INTRO + '</p>'
        page['content'].append(dict(id='illustration', type='TEXT', value=DELTA_PAGE_ILLUSTRATION))
        self.replace_page(fixture, page)
        result = resolve_operator_definition(*fixture, resource_contract_version=2)
        self.assertEqual(result['status'], 'supported', result['rejections'])
        self.assertFalse(result['value']['parameter_policy']['platform_domain_complete'])

    def test_rehashed_numeric_restrictions_are_not_unrelated_prose(self):
        """Input: canonical rehashed TEXT/TABLE constraints. Output: None. Reject numeric restrictions even without policy keywords."""
        from wqb.resource_evidence import resolve_operator_definition, validated_documentation_page
        for value in ('d>=100.', 'd<10.', 'd &gt;= 100.', 'd &lt; 10.', '100 <= d.', '10 > d.',
                      'd &#8805; 100.', 'd &#60; 10.') + PARENTHESIZED_WINDOW_CONSTRAINTS:
            for kind in ('TEXT', 'TABLE'):
                fixture = page_operator_fixture()
                ref = fixture[0]['definition_basis']['signature_premise']['evidence_ref']
                page = validated_documentation_page(ref, fixture[1], fixture[2])
                content = value if kind == 'TEXT' else dict(data=[['Expression'], [value]],
                    firstColIsHeader=False, firstRowIsTableHeader=True)
                page['content'].append(dict(id='restriction', type=kind, value=content))
                self.replace_page(fixture, page)
                updated = fixture[0]['definition_basis']['signature_premise']['evidence_ref']
                validated_documentation_page(updated, fixture[1], fixture[2])
                with self.subTest(kind=kind, value=value):
                    self.assertEqual(resolve_operator_definition(*fixture, resource_contract_version=2)['status'], 'unsupported')

    def test_rehashed_deleted_operation_and_matrix_claims_are_not_evidence(self):
        """Input: canonical page HTML deletion markers. Output: None. Deleted facts cannot become positive source premises."""
        from wqb.resource_evidence import resolve_operator_definition, validated_documentation_page
        for position in (0, 1):
            for tag in ('del', 's', 'strike', 'span hidden', 'span style="display:none"',
                        'span style="text-decoration:line-through"', 'script', 'template'):
                fixture = page_operator_fixture()
                premise = [fixture[0]['definition_basis']['signature_premise'], *fixture[0]['definition_basis']['type_premises']][position]
                page = validated_documentation_page(premise['evidence_ref'], fixture[1], fixture[2])
                block = page['content'][0 if position == 0 else 1]
                block['value'] = f'<{tag}>' + block['value'] + f'</{tag.split()[0]}>'
                self.replace_page(fixture, page, position)
                with self.subTest(position=position, tag=tag):
                    result = resolve_operator_definition(*fixture, resource_contract_version=2)
                    self.assertEqual(result['status'], 'unsupported', result)

    def test_full_page_target_timing_conflicts_survive_canonical_rehash(self):
        """Input: extra naming/cutoff facts in full FastD1 payload. Output: None. Aggregate target roles; preserve unrelated facts and explicit Delay0."""
        from wqb.resource_evidence import validated_documentation_page, resolve_timing_contract
        naming = 'Regular D1 Field: other Fast D1 Field: snt_buzz'
        reversed_cutoff = ("Delay Field Type Data Timestamp Information Captured 1 other Yesterday's market close "
            "Yesterday\u2019s End-of-day data only Fast D1 snt_buzz Today's market open Overnight news, events, pre-market moves")
        for clause in (naming, reversed_cutoff, 'Regular D1 Field: snt_buzz Fast D1 Field: other_fast_d1', 'TABLE'):
            fixture = page_timing_fixture()
            ref = fixture[0]['premises'][1]['evidence_ref']
            page = validated_documentation_page(ref, fixture[3], fixture[4])
            if clause == 'TABLE':
                value = copy.deepcopy(page['content'][1]['value'])
                value['data'][1][1], value['data'][2][1] = 'other', 'snt_buzz'
                page['content'].append(dict(id='conflict', type='TABLE', value=value))
            else:
                page['content'].append(dict(id='conflict', type='TEXT', value=clause))
            new_ref, index, texts = documentation_fixture(page)
            fixture[3].update(index)
            fixture[4].update(texts)
            for position in (1, 2):
                fixture[0]['premises'][position]['evidence_ref'] = copy.deepcopy(new_ref)
            validated_documentation_page(new_ref, fixture[3], fixture[4])
            with self.subTest(clause=clause):
                self.assertEqual(resolve_timing_contract(*fixture)['status'], 'unsupported')

    def test_complete_page_preserves_delay0_and_unrelated_named_pair_context(self):
        """Input: source-shaped Delay0 row and independent named pair. Output: None. Contexts remain distinct without suffix-based generalization."""
        from wqb.resource_evidence import validated_documentation_page, resolve_timing_contract
        fixture = page_timing_fixture()
        ref = fixture[0]['premises'][1]['evidence_ref']
        page = validated_documentation_page(ref, fixture[3], fixture[4])
        page['content'][1]['value']['data'].append(['0', 'snt_buzz', "30 minutes before today's close",
            'Close to end of today \u2013 harder to execute'])
        page['content'].append(dict(id='independent', type='TEXT',
            value='Regular D1 Field: other Fast D1 Field: other_fast_d1'))
        new_ref, index, texts = documentation_fixture(page)
        fixture[3].update(index)
        fixture[4].update(texts)
        for position in (1, 2):
            fixture[0]['premises'][position]['evidence_ref'] = copy.deepcopy(new_ref)
        result = resolve_timing_contract(*fixture)
        self.assertEqual(result['status'], 'supported', result['rejections'])


    def test_page_grammar_is_bound_to_rule_and_semantic_design_job_keys(self):
        """Input: finite page grammar version change. Output: None. Existing supported claims get distinct rule/semantic/design identities."""
        from unittest.mock import patch
        from wqb import resource_evidence as rules
        from wqb.semantic_compilation import _design_versions, _semantic_versions
        from wqb.semantic_contracts import SemanticPolicy
        fixture = page_operator_fixture()
        before = rules.resolve_operator_definition(*fixture, resource_contract_version=2)['value']
        design_before, semantic_before = _design_versions(SemanticPolicy()), _semantic_versions(SemanticPolicy(), 2)
        policy = copy.deepcopy(rules.DOCUMENTATION_PAGE_POLICY)
        policy['version'] += 1
        with patch.object(rules, 'DOCUMENTATION_PAGE_POLICY', policy):
            after = rules.resolve_operator_definition(*fixture, resource_contract_version=2)['value']
            self.assertNotEqual(before['rule_digest'], after['rule_digest'])
            self.assertNotEqual(design_before, _design_versions(SemanticPolicy()))
            self.assertNotEqual(semantic_before, _semantic_versions(SemanticPolicy(), 2))

    def test_known_settings_simulation_example_is_not_a_timing_proof(self):
        """Input: source-shaped official illustration. Output: None. Known nonproof blocks coexist with explicit policy without granting timing."""
        from wqb.resource_evidence import _page_claim_context
        settings = dict(instrumentType='EQUITY', language='FASTEXPR', maxTrade='OFF', nanHandling='OFF',
            neutralization='MARKET', pasteurization='ON', region='USA', unitHandling='VERIFY', universe='TOP3000',
            decay=0, delay=1, truncation=0.08)
        page = dict(id='simulation-settings', content=[dict(id='example', type='SIMULATION_EXAMPLE',
            value=dict(regular='ts_zscore(etz_eps, 252)', settings=settings, type='REGULAR'))])
        page = json.loads(json.dumps(page, sort_keys=True))
        _page_claim_context(page)

    def test_page_timing_and_expiry_never_generalize_to_industry(self):
        """Input: page-backed exact-field timing/expiry/scope changes. Output: None. Classify snt_buzz only; GROUP names are not timing proof."""
        from wqb.resource_evidence import REGULAR_DELAY_POLICY, resolve_timing_contract
        fixture = named_comparison_fixture()
        settings = dict(id='simulation-settings', title='How to choose the Simulation Settings', category='Getting Started',
            sequence=25, lastModified='2026-09-18T13:05:17.445496+08:00',
            content=[dict(id='policy', type='TEXT', value='<p>' + REGULAR_DELAY_POLICY + '</p>')])
        naming = fixture[0]['premises'][1]['locator']['quote']
        cutoff = fixture[0]['premises'][2]['locator']['quote']
        fast = dict(id='fast-d1-documentation', title='Fast D1 Documentation', category='Advanced Topics',
            sequence=1222, lastModified='2026-09-18T13:11:18.469684+08:00', content=[
                dict(id='naming', type='TEXT', value=naming),
                dict(id='cutoff', type='TABLE', value=dict(data=[['Delay', 'Field Type', 'Data Timestamp', 'Information Captured'],
                    ['1', 'snt_buzz', "Yesterday's market close", 'Yesterday\u2019s End-of-day data only'],
                    ['Fast D1', 'snt_buzz_fast_d1', "Today's market open", 'Overnight news, events, pre-market moves']],
                    firstColIsHeader=False, firstRowIsTableHeader=True))])
        for page, positions in ((settings, [0]), (fast, [1, 2])):
            ref, index, texts = documentation_fixture(page)
            fixture[3].update(index)
            fixture[4].update(texts)
            for position in positions:
                fixture[0]['premises'][position]['evidence_ref'] = copy.deepcopy(ref)
        fixture[2]['as_of'] = '2026-10-16T00:00:00Z'
        result = resolve_timing_contract(*fixture)
        self.assertEqual(result['status'], 'supported', result)
        self.assertFalse(result['value']['historical_pit_verified'])
        self.assertNotIn('available_at', fixture[1])
        fixture[2]['as_of'] = '2027-01-16T00:00:00Z'
        self.assertEqual(resolve_timing_contract(*fixture)['status'], 'unsupported')
        fixture[2]['as_of'] = '2026-10-16T00:00:00Z'
        fixture[0]['field_identity']['field_id'] = 'industry'
        fixture[1].update(field_id='industry', field_type='GROUP')
        self.assertEqual(resolve_timing_contract(*fixture)['status'], 'unsupported')

    def replace_page(self, fixture, page, position=0):
        """Input: operator fixture/new page dict/premise int. Output: None. Rebind capture-derived paths/hashes without changing claim quotes."""
        from wqb.resource_evidence import _digest
        record, index, texts = fixture
        premise = [record['definition_basis']['signature_premise'], *record['definition_basis']['type_premises']][position]
        old = premise['evidence_ref']['source_path']
        ref, new_index, new_texts = documentation_fixture(page, kind='operator_detail' if position == 0 else 'tutorial')
        del index[old], texts[old]
        index.update(new_index)
        texts.update(new_texts)
        for value in [premise['evidence_ref'], *record['definition']['evidence_refs']]:
            if value['source_path'] == old:
                value.update(ref)
        record['definition_basis']['definition_digest'] = _digest(record['definition'])

    def test_rehashed_contrary_context_unknown_blocks_and_new_trust_are_rejected(self):
        """Input: fully rehashed lossless pages. Output: None. Neither known schema nor favourable quote hides contrary clauses."""
        from wqb.resource_evidence import resolve_operator_definition, validated_documentation_page
        for position, clause in ((0, 'd must be even.'), (0, 'ts_delta is unavailable for REGULAR.'),
                                 (1, 'Matrix data have two values per day per instrument.'),
                                 (1, 'ts_delta requires VECTOR input.'), (1, 'Only vector input is permitted.')):
            fixture = page_operator_fixture()
            premise = [fixture[0]['definition_basis']['signature_premise'], *fixture[0]['definition_basis']['type_premises']][position]
            page = validated_documentation_page(premise['evidence_ref'], fixture[1], fixture[2])
            page['content'].insert(0, dict(id='contrary', type='TEXT', value=clause))
            self.replace_page(fixture, page, position)
            with self.subTest(clause=clause):
                self.assertEqual(resolve_operator_definition(*fixture, resource_contract_version=2)['status'], 'unsupported')
        for mode in ('unknown', 'duplicate', 'trust', 'changed_core'):
            fixture = page_operator_fixture()
            premise = fixture[0]['definition_basis']['type_premises'][0]
            page = validated_documentation_page(premise['evidence_ref'], fixture[1], fixture[2])
            if mode == 'unknown':
                page['content'][1]['type'] = 'UNKNOWN'
            elif mode == 'duplicate':
                page['content'].append(copy.deepcopy(page['content'][1]))
            elif mode == 'trust':
                page['verified'] = True
            else:
                page['content'][1]['value'] = page['content'][1]['value'].replace('one value', 'two values')
            self.replace_page(fixture, page, 1)
            with self.subTest(mode=mode):
                self.assertEqual(resolve_operator_definition(*fixture, resource_contract_version=2)['status'], 'unsupported')

    def test_unrelated_summary_change_preserves_meaning_but_changes_receipt(self):
        """Input: updated summary/full source. Output: None. No whole-page hash whitelist; changed bytes still bind the receipt."""
        from wqb.resource_evidence import resolve_operator_definition, validated_documentation_page
        fixture = page_operator_fixture()
        first = resolve_operator_definition(*fixture, resource_contract_version=2)['value']
        premise = fixture[0]['definition_basis']['type_premises'][0]
        page = validated_documentation_page(premise['evidence_ref'], fixture[1], fixture[2])
        page['content'][0]['value'] = '<style>.summary {color:green}</style><p>A revised overview of event aggregation.</p>'
        self.replace_page(fixture, page, 1)
        result = resolve_operator_definition(*fixture, resource_contract_version=2)
        self.assertEqual(result['status'], 'supported', result)
        self.assertNotEqual(first['receipt_digest'], result['value']['receipt_digest'])

    def test_page_operation_and_scoped_matrix_prove_explicit_project_subset(self):
        """Input: complete page fixtures. Output: None. Operation prose supports types with project-owned d only."""
        from wqb.resource_evidence import resolve_operator_definition
        fixture = page_operator_fixture()
        result = resolve_operator_definition(*fixture, resource_contract_version=2)
        self.assertEqual(result['status'], 'supported', result)
        self.assertEqual(result['value']['definition']['description'], DELTA_PAGE_MEANING)
        fixture[0]['definition_basis'].update(rule_id='ts_delta', rule_version=1)
        self.assertEqual(resolve_operator_definition(*fixture, resource_contract_version=2)['status'], 'unsupported')

    def test_shared_page_adapter_validates_complete_duplicate_payload(self):
        """Input: independently rehashed source tampering. Output: None. Duplicate or rendered changes cannot grant trust."""
        from wqb import resource_evidence as rules
        fixture = page_operator_fixture()
        ref = fixture[0]['definition_basis']['signature_premise']['evidence_ref']
        page = rules.validated_documentation_page(ref, fixture[1], fixture[2])
        self.assertEqual(page['id'], 'ts_delta')
        for needle, replacement in [('## ts_delta', '## other'), ('"endpoint": "/operators/ts_delta"', '"endpoint": "/operators/other"'),
                                    ('"error": null', '"error": "cancelled"'), ('"type": "TABLE"', '"type": "UNKNOWN"')]:
            changed = copy.deepcopy(fixture)
            path = ref['source_path']
            text = changed[2][path].replace(needle, replacement, 1)
            _, body = __import__('wqb.knowledge_contracts', fromlist=['parse_markdown_front_matter']).parse_markdown_front_matter(text)
            changed[1][path]['content_hash'] = hashlib.sha256(body.encode()).hexdigest()
            changed[1][path].pop('file_sha256')
            metadata = {key: value for key, value in changed[1][path].items() if key != 'file_sha256'}
            changed[2][path] = render_front_matter(metadata) + body
            changed_ref = dict(ref, sha256=metadata['content_hash'])
            with self.subTest(needle=needle), self.assertRaises(ValueError):
                rules.validated_documentation_page(changed_ref, changed[1], changed[2])


def material(body="## Timing\nExact policy.\n## Other\nUnrelated.\n", suffix="md"):
    """Input: body/suffix str. Output: premise/index/texts tuple. Build full hashed source fixtures."""
    path = "raw/platform/learn/policy." + suffix
    digest = hashlib.sha256(body.encode()).hexdigest()
    row = dict(path=path, content_hash=digest, captured_at="2026-10-15T00:00:00Z",
               source_type="platform_learn_material", source_family="raw/platform/learn")
    text = render_front_matter(row) + body if suffix == "md" else body
    row["file_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    premise = dict(evidence_ref=dict(source_path=path, sha256=digest,
                   capture_date="2026-10-15", kind="documented"),
                   locator=dict(kind="markdown_quote", heading="Timing", quote="Exact policy."))
    return premise, {path: row}, {path: text}


def timing_contract():
    """Input: none. Output: dict. Supply a shape-only timing contract, not authority."""
    return dict(kind="platform_execution_policy", scope=dict(SCOPE), cutoff_class="regular_delay_1",
                field_identity=dict(dataset_id="d", field_id="f"), premises=[material()[0]],
                rule_id="regular_delay_1", rule_version=1, historical_pit_verified=False)


def definition_basis():
    """Input: none. Output: dict. Supply a shape-only derivation basis."""
    return dict(operator="ts_delta", signature_premise=material()[0], type_premises=[material()[0]],
                rule_id="ts_delta", rule_version=1, definition_digest="a" * 64)


def operator_fixture(operator="group_rank", *, integer=True):
    """Input: operator str/integer bool. Output: record/index/texts dicts. Mix actual passages with a labelled fictional window fact."""
    descriptions = {
        "ts_delta": "Calculates the difference between a value and its delayed version over a specified period. Useful for measuring changes or momentum in time-series data.",
        "group_rank": "Ranks each element within its group based on the input field, assigning a value between 0.0 and 1.0. This helps compare items within the same group, such as stocks in the same industry.",
        "group_neutralize": "Neutralizes Alpha values within each specified group by subtracting the group mean from each value. Groups can be industry, sector, country, or any custom grouping.",
    }
    names = ["x", "d" if operator == "ts_delta" else "group"]
    types = ["MATRIX", "INTEGER" if operator == "ts_delta" else "GROUP"]
    block = (f"- Source id: `{operator}`\n- Scope: ['COMBO', 'REGULAR']\n"
             f"- Definition: `{operator}({', '.join(names)})`\n- Description: {descriptions[operator]}")
    matrix = ("This is unlike regular matrix data that you work with, which has one value per day per instrument. "
              "Now, whenever you write an Alpha expression, the end result is a matrix of Alpha values which is the position that is taken in the market. "
              "And all the operators on platform are made for matrix input, hence use the matrix operator only after using the vec_ operators to convert the vector data field to matrix field.")
    group = ("Group Data Fields are fields which have information about instrument segregation into various groups. "
             "They are supposed to be used as an input to the group operator.")
    window = "For Fast Expression ts_delta(x, d), d must be a positive integer number of days."
    first, index, texts = material(f"### `{operator}`\n{block}\n")
    first["locator"].update(heading=f"`{operator}`", quote=block)
    body = "## Vector Data Fields\n" + matrix + "\n## Group Data Fields\n" + group + "\n"
    if integer:
        body += "## Fast Expression time-series parameters\n" + window + "\n"
    doc, other_index, other_texts = material(body)
    old = doc["evidence_ref"]["source_path"]
    path = "raw/platform/learn/types.md"
    other_index[path] = other_index.pop(old)
    other_index[path]["path"] = path
    # Re-render because the source identity in front matter is also verified.
    other_texts = {path: render_front_matter({k: v for k, v in other_index[path].items() if k != "file_sha256"}) + body}
    other_index[path]["file_sha256"] = hashlib.sha256(other_texts[path].encode()).hexdigest()
    index.update(other_index)
    texts.update(other_texts)
    doc["evidence_ref"]["source_path"] = path
    first["evidence_ref"]["experiment_refs"] = []
    doc["evidence_ref"]["experiment_refs"] = []
    premises = []
    for heading, quote in [("Vector Data Fields", matrix), ("Group Data Fields", group)] + (
            [("Fast Expression time-series parameters", window)] if integer and operator == "ts_delta" else []):
        p = copy.deepcopy(doc)
        p["locator"].update(heading=heading, quote=quote)
        premises.append(p)
    definition = dict(description=descriptions[operator], input_types=["MATRIX"], output_type="MATRIX",
                      parameters=[dict(name=n, type=t, required=True) for n, t in zip(names, types)],
                      evidence_refs=[first["evidence_ref"], doc["evidence_ref"]])
    if operator != "ts_delta":
        definition["input_types"].append("GROUP")
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    record = dict(operator=operator, definition=definition, definition_basis=dict(
        operator=operator, signature_premise=first, type_premises=premises,
        rule_id=operator, rule_version=1, definition_digest=digest))
    return record, index, texts


class OperatorDefinitionResolutionTests(unittest.TestCase):
    def test_explicit_project_window_rule_without_official_integer_domain(self):
        """Input: fictional sourced fixture. Output: None; assert explicit project provenance, not platform typing."""
        from wqb import resource_evidence
        fixture = operator_fixture('ts_delta', integer=False)
        self.assertEqual(self.resolve(fixture)['status'], 'unsupported')
        fixture[0]['definition_basis'].update(rule_id='ts_delta_project_window', rule_version=2)
        result = self.resolve(fixture)
        self.assertEqual(result['status'], 'supported', result)
        receipt = result['value']
        self.assertEqual(receipt['parameter_policy'], resource_evidence.PROJECT_WINDOW_POLICY)
        self.assertEqual(receipt['parameter_policy']['owner'], 'project')
        self.assertFalse(receipt['parameter_policy']['platform_domain_complete'])
        self.assertNotIn('parameter_constraints', receipt)
        self.assertEqual(receipt['definition'], fixture[0]['definition'])
        self.assertEqual(self.resolve(fixture, version=1)['status'], 'unsupported')

    def test_project_window_preserves_contrary_constraints_and_source_guards(self):
        """Input: fictional source changes. Output: None; reject unhandled restrictions/defaults and missing facts."""
        for clause in ('d must be even.', 'd must be greater than 22.',
                       'For Fast Expression ts_delta(x, d), d must be a positive integer number of days. d defaults to zero.'):
            with self.subTest(clause=clause):
                fixture = operator_fixture('ts_delta', integer=False)
                fixture[0]['definition_basis'].update(rule_id='ts_delta_project_window', rule_version=2)
                path = 'raw/platform/learn/types.md'
                body = fixture[2][path].split('---\n', 2)[-1]
                self.rehash(fixture, path, body + '## Time-series parameters\n' + clause + '\n')
                self.assertEqual(self.resolve(fixture)['status'], 'unsupported')
        fixture = operator_fixture('ts_delta')
        fixture[0]['definition_basis'].update(rule_id='ts_delta_project_window', rule_version=2)
        self.assertEqual(self.resolve(fixture)['status'], 'supported')
        for mode in ('matrix', 'meaning', 'signature', 'type', 'tamper', 'rule_version'):
            with self.subTest(mode=mode):
                changed = copy.deepcopy(fixture)
                if mode == 'matrix':
                    changed[0]['definition_basis']['type_premises'] = changed[0]['definition_basis']['type_premises'][1:]
                elif mode == 'meaning':
                    changed[0]['definition']['description'] = 'Unknown meaning.'
                elif mode == 'signature':
                    changed[0]['definition_basis']['signature_premise']['locator']['heading'] = 'unknown'
                elif mode == 'type':
                    changed[0]['definition']['input_types'] = ['VECTOR']
                elif mode == 'tamper':
                    changed[2][next(iter(changed[2]))] += 'changed'
                else:
                    changed[0]['definition_basis']['rule_version'] = 1
                self.assertEqual(self.resolve(changed)['status'], 'unsupported')

    def test_project_window_signature_defaults_remain_bounded_positive_integers(self):
        """Input: documented literal defaults in fictional sources. Output: None; project subset never overrides a contrary default."""
        from wqb.resource_evidence import PROJECT_WINDOW_POLICY
        for default in (1, 17, PROJECT_WINDOW_POLICY['maximum'], 0, -1,
                        PROJECT_WINDOW_POLICY['maximum'] + 1, True, 1.5):
            with self.subTest(default=default):
                fixture = operator_fixture('ts_delta', integer=False)
                row = fixture[0]
                row['definition_basis'].update(rule_id='ts_delta_project_window', rule_version=2)
                premise = row['definition_basis']['signature_premise']
                premise['locator']['quote'] = premise['locator']['quote'].replace(
                    'ts_delta(x, d)', f'ts_delta(x, d={default})')
                row['definition']['parameters'][1].update(required=False, default=default)
                self.rehash(fixture, premise['evidence_ref']['source_path'],
                            '### `ts_delta`\n' + premise['locator']['quote'] + '\n')
                expected = 'supported' if type(default) is int and 1 <= default <= PROJECT_WINDOW_POLICY['maximum'] else 'unsupported'
                self.assertEqual(self.resolve(fixture)['status'], expected)

    def receipt_fixture(self, operator="ts_delta", kind="operator_detail", *, extra=None, integer=True):
        """Input: operator/kind str, optional payload dict, integer bool. Output: fixture/receipt. Model exact writer bytes without IO."""
        fixture = operator_fixture(operator, integer=integer)
        row, index, texts = fixture
        payload = dict(name=operator, category="Time Series" if operator == "ts_delta" else "Group",
                       scope=["COMBO", "REGULAR"], level="ALL", documentation="/operators/" + operator,
                       definition=operator + ("(x, d)" if operator == "ts_delta" else "(x, group)"),
                       description=row["definition"]["description"])
        payload.update(extra or {})
        receipt = dict(generated_at="2026-10-15T00:00:00Z", target=dict(kind=kind),
                       endpoint="/operators", payload=[payload], error=None)
        if kind != "operators":
            receipt["target"]["id"] = operator
        if kind == "operator_detail":
            receipt.update(endpoint="/operators/" + operator, payload=payload)
        block = (f"- Source id: `{operator}`\n- Scope: {payload['scope']}\n- Level: {payload['level']}\n"
                 f"- Documentation: {payload['documentation']}\n- Definition: `{payload['definition']}`\n"
                 f"- Description: {payload['description']}")
        prefix = f"\n# Operators\n\nRecord count: 1\n\n## {payload['category']}\n\n### `{operator}`\n\n{block}\n"
        self.bind_receipt(fixture, receipt, prefix, [payload])
        row["definition_basis"]["signature_premise"]["locator"]["quote"] = block
        return fixture, receipt

    def bind_receipt(self, fixture, receipt, prefix=None, rows=None):
        """Input: fixture/receipt, optional prefix str/rows list. Output: None. Rebind canonical provenance after test mutation."""
        from wqb.resource_evidence import _digest
        row, index, texts = fixture
        ref = row["definition_basis"]["signature_premise"]["evidence_ref"]
        old = ref["source_path"]
        if prefix is None:
            prefix = texts[old].split("---\n", 2)[-1].split("\n## Raw GET Receipt", 1)[0]
        if rows is None:
            payload = receipt["payload"]
            rows = ([payload] if receipt["target"]["kind"] == "operator_detail" else
                    payload["results"] if isinstance(payload, dict) else payload)
        path = "raw/platform/learn/2026-10-15/subset-" + _digest(receipt) + "/operators.md"
        index[path] = index.pop(old)
        texts[path] = texts.pop(old)
        index[path].update(path=path, source_path=path, capture_tool="scripts/capture_learn_material.py",
                           content_status="raw_markdown", record_count=len(rows), payload_hash=_digest(rows),
                           update_check="compare record count, content hash, and platform endpoint against the previous Learn capture",
                           compiled_targets=["wiki/30_template_and_operator_patterns.md", "machine/operator_ledger.jsonl"])
        for premise in [row["definition_basis"]["signature_premise"], *row["definition_basis"]["type_premises"]]:
            if premise["evidence_ref"]["source_path"] == old:
                premise["evidence_ref"]["source_path"] = path
        for evidence in row["definition"]["evidence_refs"]:
            if evidence["source_path"] == old:
                evidence["source_path"] = path
        body = prefix + "\n## Raw GET Receipt\n\n```json\n" + json.dumps(
            receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n"
        self.rehash(fixture, path, body)

    def test_canonical_duplicate_receipts_all_operators_and_endpoints(self):
        for operator in ("ts_delta", "group_rank", "group_neutralize"):
            for kind in ("operators", "operator", "operator_detail"):
                with self.subTest(operator=operator, kind=kind):
                    fixture, _ = self.receipt_fixture(operator, kind)
                    before = copy.deepcopy(fixture)
                    result = self.resolve(fixture)
                    self.assertEqual(result["status"], "supported", result)
                    self.assertEqual(fixture, before)
                    path = fixture[0]["definition_basis"]["signature_premise"]["evidence_ref"]["source_path"]
                    source = next(item for item in result["value"]["sources"] if item["source_path"] == path)
                    self.assertEqual(source["file_sha256"], hashlib.sha256(fixture[2][path].encode()).hexdigest())

    def test_receipt_cannot_hide_extra_payload_facts_for_any_operator(self):
        for operator in ("ts_delta", "group_rank", "group_neutralize"):
            for key in ("parameters", "constraints", "input_types", "output_type", "defaults", "unknown"):
                with self.subTest(operator=operator, key=key):
                    fixture, _ = self.receipt_fixture(operator, extra={key: {"d": "even positive integer"}})
                    self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_receipt_schema_identity_and_complete_body_fail_closed(self):
        for change in ("endpoint", "target", "error", "time", "description", "duplicate", "schema", "tail", "prefix"):
            with self.subTest(change=change):
                fixture, receipt = self.receipt_fixture()
                prefix = None
                if change == "endpoint":
                    receipt["endpoint"] = "/tutorial-pages/ts_delta"
                elif change == "target":
                    receipt["target"]["id"] = "group_rank"
                elif change == "error":
                    receipt["error"] = {"message": "failed"}
                elif change == "time":
                    receipt["generated_at"] = "2026-10-14T00:00:00Z"
                elif change == "description":
                    receipt["payload"]["description"] += " d must be even."
                elif change == "duplicate":
                    receipt["target"] = {"kind": "operators"}
                    receipt["endpoint"] = "/operators"
                    receipt["payload"] = [receipt["payload"], receipt["payload"]]
                elif change == "schema":
                    receipt["constraints"] = "d must be even"
                elif change == "prefix":
                    path = fixture[0]["definition_basis"]["signature_premise"]["evidence_ref"]["source_path"]
                    prefix = fixture[2][path].split("---\n", 2)[-1].split("\n## Raw GET Receipt", 1)[0]
                    prefix = prefix.replace("# Operators", "# Python Alpha")
                self.bind_receipt(fixture, receipt, prefix)
                if change == "tail":
                    path = fixture[0]["definition_basis"]["signature_premise"]["evidence_ref"]["source_path"]
                    self.rehash(fixture, path, fixture[2][path].split("---\n", 2)[-1] + "<!-- d must be even -->\n")
                self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_receipt_never_supplies_missing_integer_fact(self):
        fixture, _ = self.receipt_fixture(integer=False)
        self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_receipt_paginated_exact_selection_checks_unrendered_rows(self):
        for extra in ({}, {"constraints": "hidden group requirement"}):
            fixture, receipt = self.receipt_fixture("group_rank", "operator")
            other = dict(receipt["payload"][0], name="other_operator", definition="other_operator(x)",
                         documentation="/operators/other_operator")
            other.update(extra)
            receipt["payload"] = dict(results=[other, *receipt["payload"]], count=2, next=None, previous=None)
            self.bind_receipt(fixture, receipt, rows=[receipt["payload"]["results"][1]])
            result = self.resolve(fixture)
            self.assertEqual(result["status"], "unsupported" if extra else "supported", result)
        for extra in ({"unknown": "hidden"}, {"count": True}, {"next": "/operators?offset=2"}):
            fixture, receipt = self.receipt_fixture("group_rank", "operator")
            rows = receipt["payload"]
            receipt["payload"] = dict(results=rows, count=1, next=None, previous=None)
            receipt["payload"].update(extra)
            self.bind_receipt(fixture, receipt, rows=rows)
            self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_receipt_header_provenance_cannot_be_forged(self):
        for key, bad in (("capture_tool", "unknown.py"), ("content_status", "preview"),
                         ("payload_hash", "0" * 64), ("record_count", 9), ("path", "raw/platform/learn/other.md"),
                         ("constraints", "d must be even"), ("update_check", "d must be even"),
                         ("compiled_targets", ["unknown/constraints.md"])):
            with self.subTest(key=key):
                fixture, _ = self.receipt_fixture("group_neutralize")
                ref = fixture[0]["definition_basis"]["signature_premise"]["evidence_ref"]
                path = ref["source_path"]
                body = fixture[2][path].split("---\n", 2)[-1]
                fixture[1][path][key] = bad
                self.rehash(fixture, path, body)
                self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_receipt_full_card_mismatch_and_hidden_clauses_reject(self):
        for operator in ("ts_delta", "group_rank", "group_neutralize"):
            for key, bad in (("scope", ["SUPERALPHA"]), ("definition", operator + "(group, x)"),
                             ("description", "d must be a positive even integer."),
                             ("description", "<!-- hidden constraint -->"),
                             ("level", {"constraint": "hidden"}), ("documentation", "https://unknown.invalid")):
                with self.subTest(operator=operator, key=key, bad=bad):
                    fixture, receipt = self.receipt_fixture(operator)
                    receipt["payload"][key] = bad
                    self.bind_receipt(fixture, receipt)
                    self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_unrecognized_tutorial_receipt_remains_explicitly_unsupported(self):
        fixture = operator_fixture("ts_delta")
        path = fixture[0]["definition_basis"]["type_premises"][0]["evidence_ref"]["source_path"]
        body = fixture[2][path].split("---\n", 2)[-1]
        receipt = dict(generated_at="2026-10-15T00:00:00Z", target=dict(kind="tutorial", id="types"),
                       endpoint="/tutorial-pages/types", payload={"content": body}, error=None)
        self.rehash(fixture, path, body + "\n## Raw GET Receipt\n\n```json\n" + json.dumps(receipt) + "\n```\n")
        self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_receipt_duplicate_json_keys_and_multiple_receipts_reject(self):
        for duplicate in (False, True):
            fixture, _ = self.receipt_fixture("group_rank")
            path = fixture[0]["definition_basis"]["signature_premise"]["evidence_ref"]["source_path"]
            body = fixture[2][path].split("---\n", 2)[-1]
            if duplicate:
                body += body[body.index("\n## Raw GET Receipt"):]
            else:
                body = body.replace('"error": null', '"error": "failure", "error": null')
            self.rehash(fixture, path, body)
            self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def rehash(self, fixture, path, body):
        """Input: fixture/path/body. Output: None. Rebind valid source hashes and basis after an intentional source change."""
        row, index, texts = fixture
        digest = hashlib.sha256(body.encode()).hexdigest()
        index[path]["content_hash"] = digest
        texts[path] = render_front_matter({k: v for k, v in index[path].items() if k != "file_sha256"}) + body
        index[path]["file_sha256"] = hashlib.sha256(texts[path].encode()).hexdigest()
        for ref in row["definition"]["evidence_refs"]:
            if ref["source_path"] == path:
                ref["sha256"] = digest
        basis = row["definition_basis"]
        for premise in [basis["signature_premise"], *basis["type_premises"]]:
            if premise["evidence_ref"]["source_path"] == path:
                premise["evidence_ref"]["sha256"] = digest
        basis["definition_digest"] = hashlib.sha256(json.dumps(row["definition"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

    def resolve(self, fixture, version=2):
        """Input: fixture tuple/version int. Output: result dict. Call the pure public resolver."""
        from wqb.resource_evidence import resolve_operator_definition
        return resolve_operator_definition(*fixture, resource_contract_version=version)

    def test_supported_cross_source_definition(self):
        for operator in ("ts_delta", "group_rank", "group_neutralize"):
            with self.subTest(operator=operator):
                fixture = operator_fixture(operator)
                before = copy.deepcopy(fixture)
                result = self.resolve(fixture)
                self.assertEqual(result["status"], "supported", result)
                self.assertEqual(result["value"]["definition"], fixture[0]["definition"])
                self.assertEqual(len(result["value"]["sources"]), 2)
                self.assertEqual(len(result["value"]["receipt_digest"]), 64)
                self.assertEqual(fixture, before)

    def test_signature_only_never_proves_types(self):
        fixture = operator_fixture()
        fixture[0]["definition_basis"]["type_premises"] = [fixture[0]["definition_basis"]["signature_premise"]]
        self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_wrong_family_or_unrelated_quote_rejected(self):
        for mode in ("family", "unrelated", "tamper", "digest", "rule", "version"):
            with self.subTest(mode=mode):
                fixture = operator_fixture()
                row, index, texts = fixture
                if mode == "family":
                    index[next(iter(index))]["source_type"] = "platform_api"
                elif mode == "unrelated":
                    row["definition_basis"]["type_premises"][0]["locator"].update(heading="Brain Python Alphas")
                elif mode == "tamper":
                    texts[next(iter(texts))] += "tampered"
                elif mode == "digest":
                    row["definition_basis"]["definition_digest"] = "a" * 64
                elif mode == "rule":
                    row["definition_basis"]["rule_version"] = 99
                self.assertEqual(self.resolve(fixture, True if mode == "version" else 2)["status"], "unsupported")

    def test_missing_parameter_fact_or_conflict_rejected(self):
        result = self.resolve(operator_fixture("ts_delta", integer=False))
        self.assertEqual(result["status"], "unsupported")
        self.assertIn("integer", result["rejections"][0]["message"])
        fixture = operator_fixture()
        fixture[0]["definition"]["parameters"][0]["type"] = "VECTOR"
        self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_v2_audit_and_proposal_share_resolver(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from wqb.knowledge_compile import _coverage_operator_supported
        from wqb.semantic_compilation import _definition_supported
        row, index, texts = operator_fixture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for path, text in texts.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode())
            self.assertTrue(_coverage_operator_supported(row, texts, source_index=index, resource_contract_version=2))
            self.assertTrue(_definition_supported(row, root, index, resource_contract_version=2))
            row["definition_basis"]["rule_version"] = 99
            self.assertFalse(_coverage_operator_supported(row, texts, source_index=index, resource_contract_version=2))
            self.assertFalse(_definition_supported(row, root, index, resource_contract_version=2))

    def test_direct_typed_v1_definition_unchanged(self):
        from wqb.knowledge_compile import _coverage_operator_supported
        fixture = operator_fixture()
        self.assertEqual(self.resolve(fixture, 1)["status"], "unsupported")
        row = fixture[0]
        path = row["definition"]["evidence_refs"][0]["source_path"]
        direct = json.dumps(dict(operator=row["operator"], definition=row["definition"]))
        legacy = copy.deepcopy(row)
        legacy.pop("definition_basis")
        legacy["definition"]["evidence_refs"] = [legacy["definition"]["evidence_refs"][0]]
        self.assertTrue(_coverage_operator_supported(legacy, {path: direct}))

    def test_hidden_conflicting_signature_or_types_rejected(self):
        for extra in ("- Definition: `group_rank(group, x)`", "- Input types: `VECTOR`", "- Scope: ['COMBO']"):
            with self.subTest(extra=extra):
                fixture = operator_fixture()
                premise = fixture[0]["definition_basis"]["signature_premise"]
                self.rehash(fixture, premise["evidence_ref"]["source_path"],
                            "### `group_rank`\n" + premise["locator"]["quote"] + "\n" + extra + "\n")
                self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_negated_meaning_and_other_language_rejected(self):
        for mode in ("negated", "python", "combo"):
            fixture = operator_fixture()
            row = fixture[0]
            premise = row["definition_basis"]["signature_premise"]
            if mode == "negated":
                row["definition"]["description"] += " This description does not apply to this operator."
                premise["locator"]["quote"] += " This description does not apply to this operator."
            else:
                premise["locator"]["quote"] = premise["locator"]["quote"].replace("['COMBO', 'REGULAR']", "['" + mode.upper() + "']")
            self.rehash(fixture, premise["evidence_ref"]["source_path"], "### `group_rank`\n" + premise["locator"]["quote"] + "\n")
            self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def test_integer_fact_has_no_invented_required_heading(self):
        fixture = operator_fixture("ts_delta")
        premise = fixture[0]["definition_basis"]["type_premises"][-1]
        path = premise["evidence_ref"]["source_path"]
        body = fixture[2][path].split("---\n", 2)[-1].replace("## Fast Expression time-series parameters", "## Time-series operator reference")
        premise["locator"]["heading"] = "Time-series operator reference"
        self.rehash(fixture, path, body)
        self.assertEqual(self.resolve(fixture)["status"], "supported")

    def test_optional_ref_defaults_and_window_signature_literals(self):
        fixture = operator_fixture()
        basis = fixture[0]["definition_basis"]
        # Optional empty evidence fields do not change source identity.
        for premise in [basis["signature_premise"], *basis["type_premises"]]:
            premise["evidence_ref"].pop("experiment_refs", None)
        self.assertEqual(self.resolve(fixture)["status"], "supported")
        for default in ("1", "True", "0", "1.5", "other()"):
            with self.subTest(default=default):
                fixture = operator_fixture("ts_delta")
                row = fixture[0]
                premise = row["definition_basis"]["signature_premise"]
                premise["locator"]["quote"] = premise["locator"]["quote"].replace("ts_delta(x, d)", "ts_delta(x, d=" + default + ")")
                value = {"1": 1, "True": True, "0": 0, "1.5": 1.5, "other()": 1}[default]
                row["definition"]["parameters"][1].update(required=False, default=value)
                self.rehash(fixture, premise["evidence_ref"]["source_path"], "### `ts_delta`\n" + premise["locator"]["quote"] + "\n")
                self.assertEqual(self.resolve(fixture)["status"], "supported" if default == "1" else "unsupported")

    def test_conflicting_referenced_capture_and_duplicate_heading_rejected(self):
        for mode in ("cross_source", "duplicate"):
            fixture = operator_fixture()
            row, _, texts = fixture
            signature = row["definition_basis"]["signature_premise"]
            block = "### `group_rank`\n" + signature["locator"]["quote"] + "\n"
            if mode == "duplicate":
                self.rehash(fixture, signature["evidence_ref"]["source_path"], block + block)
            else:
                path = row["definition_basis"]["type_premises"][0]["evidence_ref"]["source_path"]
                body = texts[path].split("---\n", 2)[-1]
                self.rehash(fixture, path, body + block.replace("group_rank(x, group)", "group_rank(group, x)"))
            self.assertEqual(self.resolve(fixture)["status"], "unsupported")

    def assert_entry_status(self, fixture, expected):
        """Input: fixture tuple/status str. Output: None. Verify resolver plus both v2 gates against complete temporary sources."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from wqb.knowledge_compile import _coverage_operator_supported
        from wqb.semantic_compilation import _definition_supported
        row, index, texts = fixture
        self.assertEqual(self.resolve(fixture)["status"], expected)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for path, text in texts.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode())
            self.assertEqual(_coverage_operator_supported(row, texts, source_index=index, resource_contract_version=2), expected == "supported")
            self.assertEqual(_definition_supported(row, root, index, resource_contract_version=2), expected == "supported")

    def test_type_premise_full_context_rejects_exclusions(self):
        additions = (
            "These rules are not for REGULAR Fast Expression.",
            "This applies only to Python Alphas.",
            "Exception: group_rank takes VECTOR input, not MATRIX input.",
            "For group_neutralize the group argument is not GROUP.",
            "This historical example has no specified expression scope.",
        )
        for operator in ("group_rank", "group_neutralize"):
            for role in (0, 1):
                for addition in additions:
                    for quote_suffix in (False, True):
                        with self.subTest(operator=operator, role=role, addition=addition, quote_suffix=quote_suffix):
                            fixture = operator_fixture(operator)
                            premise = fixture[0]["definition_basis"]["type_premises"][role]
                            path = premise["evidence_ref"]["source_path"]
                            body = fixture[2][path].split("---\n", 2)[-1]
                            quote = premise["locator"]["quote"]
                            body = body.replace(quote, quote + " " + addition)
                            if quote_suffix:
                                premise["locator"]["quote"] += " " + addition
                            self.rehash(fixture, path, body)
                            self.assert_entry_status(fixture, "unsupported")

    def test_type_premise_ancestor_and_container_scope_checked(self):
        for prefix in ("# Brain Python Alphas\n", "# SuperAlpha Operators\n", "# Unscoped examples\n",
                       "# Documentation Pages\nPython Alphas only.\n", "Python only.\n"):
            with self.subTest(prefix=prefix):
                fixture = operator_fixture()
                path = fixture[0]["definition_basis"]["type_premises"][0]["evidence_ref"]["source_path"]
                body = fixture[2][path].split("---\n", 2)[-1]
                self.rehash(fixture, path, prefix + body)
                self.assert_entry_status(fixture, "unsupported")

    def test_all_integer_constraints_apply_independent_of_order(self):
        from itertools import permutations
        positive = "For Fast Expression ts_delta(x, d), d must be a positive integer number of days."
        nonnegative = positive.replace("positive", "non-negative")
        for default in (0, 1):
            for constraints in ((nonnegative,), *permutations((positive, nonnegative))):
                for reverse_premises in (False, True):
                    with self.subTest(default=default, constraints=constraints, reverse=reverse_premises):
                        fixture = operator_fixture("ts_delta")
                        row = fixture[0]
                        basis = row["definition_basis"]
                        signature = basis["signature_premise"]
                        signature["locator"]["quote"] = signature["locator"]["quote"].replace("ts_delta(x, d)", f"ts_delta(x, d={default})")
                        row["definition"]["parameters"][1].update(required=False, default=default)
                        self.rehash(fixture, signature["evidence_ref"]["source_path"], "### `ts_delta`\n" + signature["locator"]["quote"] + "\n")
                        window = basis["type_premises"][-1]
                        path = window["evidence_ref"]["source_path"]
                        body = fixture[2][path].split("---\n", 2)[-1].replace(positive, " ".join(constraints))
                        windows = []
                        for constraint in constraints:
                            premise = copy.deepcopy(window)
                            premise["locator"]["quote"] = constraint
                            windows.append(premise)
                        basis["type_premises"][-1:] = windows[::-1] if reverse_premises else windows
                        self.rehash(fixture, path, body)
                        expected = "unsupported" if default == 0 and positive in constraints else "supported"
                        self.assert_entry_status(fixture, expected)

    def test_unquoted_window_constraint_still_applies(self):
        fixture = operator_fixture("ts_delta")
        row = fixture[0]
        signature = row["definition_basis"]["signature_premise"]
        signature["locator"]["quote"] = signature["locator"]["quote"].replace("ts_delta(x, d)", "ts_delta(x, d=0)")
        row["definition"]["parameters"][1].update(required=False, default=0)
        self.rehash(fixture, signature["evidence_ref"]["source_path"], "### `ts_delta`\n" + signature["locator"]["quote"] + "\n")
        window = row["definition_basis"]["type_premises"][-1]
        positive = window["locator"]["quote"]
        window["locator"]["quote"] = positive.replace("positive", "non-negative")
        path = window["evidence_ref"]["source_path"]
        body = fixture[2][path].split("---\n", 2)[-1].replace(positive, window["locator"]["quote"] + " " + positive)
        self.rehash(fixture, path, body)
        self.assert_entry_status(fixture, "unsupported")

    def test_other_applicable_window_section_cannot_be_omitted(self):
        fixture = operator_fixture("ts_delta")
        row = fixture[0]
        signature = row["definition_basis"]["signature_premise"]
        signature["locator"]["quote"] = signature["locator"]["quote"].replace("ts_delta(x, d)", "ts_delta(x, d=0)")
        row["definition"]["parameters"][1].update(required=False, default=0)
        self.rehash(fixture, signature["evidence_ref"]["source_path"], "### `ts_delta`\n" + signature["locator"]["quote"] + "\n")
        window = row["definition_basis"]["type_premises"][-1]
        positive = window["locator"]["quote"]
        window["locator"]["quote"] = positive.replace("positive", "non-negative")
        path = window["evidence_ref"]["source_path"]
        body = fixture[2][path].split("---\n", 2)[-1].replace(positive, window["locator"]["quote"])
        self.rehash(fixture, path, body + "\n## Time-series operator reference\n" + positive + "\n")
        self.assert_entry_status(fixture, "unsupported")

    def test_window_leaf_context_cannot_override_explicit_language(self):
        for heading in ("Python Alphas", "SuperAlpha parameters", "Time-series parameters (Python only)"):
            fixture = operator_fixture("ts_delta")
            window = fixture[0]["definition_basis"]["type_premises"][-1]
            path = window["evidence_ref"]["source_path"]
            old = window["locator"]["heading"]
            body = fixture[2][path].split("---\n", 2)[-1].replace("## " + old, "## " + heading)
            window["locator"]["heading"] = heading
            self.rehash(fixture, path, body)
            self.assert_entry_status(fixture, "unsupported")

    def test_unknown_operator_capture_exception_rejected(self):
        fixture = operator_fixture()
        premise = fixture[0]["definition_basis"]["signature_premise"]
        path = premise["evidence_ref"]["source_path"]
        body = "### `group_rank`\n" + premise["locator"]["quote"] + "\n- Exception: REGULAR input x must be VECTOR, not MATRIX.\n"
        self.rehash(fixture, path, body)
        self.assert_entry_status(fixture, "unsupported")

    def test_bounded_document_container_remains_supported(self):
        fixture = operator_fixture()
        path = fixture[0]["definition_basis"]["type_premises"][0]["evidence_ref"]["source_path"]
        body = fixture[2][path].split("---\n", 2)[-1]
        self.rehash(fixture, path, "# Documentation Pages\n\nRecord count: 39\n\n" + body)
        self.assert_entry_status(fixture, "supported")

    def test_unquoted_unknown_window_constraints_fail_closed(self):
        clauses = (
            (1, "For Fast Expression ts_delta(x, d), d must be a positive even integer number of days."),
            (0, "For Fast Expression ts_delta(x, d), d must be greater than zero."),
            (1, "For Fast Expression ts_delta(x, d), d must be an odd integer."),
        )
        for default, clause in clauses:
            for heading in ("Time-series operator reference", "Additional window constraints", "Additional constraints"):
                for before in (False, True):
                    with self.subTest(default=default, clause=clause, heading=heading, before=before):
                        fixture = operator_fixture("ts_delta")
                        row = fixture[0]
                        signature = row["definition_basis"]["signature_premise"]
                        signature["locator"]["quote"] = signature["locator"]["quote"].replace("ts_delta(x, d)", f"ts_delta(x, d={default})")
                        row["definition"]["parameters"][1].update(required=False, default=default)
                        self.rehash(fixture, signature["evidence_ref"]["source_path"], "### `ts_delta`\n" + signature["locator"]["quote"] + "\n")
                        window = row["definition_basis"]["type_premises"][-1]
                        path = window["evidence_ref"]["source_path"]
                        body = fixture[2][path].split("---\n", 2)[-1]
                        if default == 0:
                            positive = window["locator"]["quote"]
                            window["locator"]["quote"] = positive.replace("positive", "non-negative")
                            body = body.replace(positive, window["locator"]["quote"])
                        extra = "## " + heading + "\n" + clause + "\n"
                        self.rehash(fixture, path, extra + body if before else body + extra)
                        self.assert_entry_status(fixture, "unsupported")

    def test_unknown_window_only_parameter_relation_is_not_ignored(self):
        for clause in ("d must be greater than zero.", "d must be a positive even integer."):
            fixture = operator_fixture("ts_delta")
            path = fixture[0]["definition_basis"]["type_premises"][-1]["evidence_ref"]["source_path"]
            body = fixture[2][path].split("---\n", 2)[-1]
            self.rehash(fixture, path, body + "\n## Additional window constraints\n" + clause + "\n")
            self.assert_entry_status(fixture, "unsupported")

    def test_unrelated_sections_do_not_become_window_constraints(self):
        fixture = operator_fixture("ts_delta")
        path = fixture[0]["definition_basis"]["type_premises"][-1]["evidence_ref"]["source_path"]
        body = fixture[2][path].split("---\n", 2)[-1]
        self.rehash(fixture, path, body + "\n## Brain Python Alphas\nPython parameters configure a lookback window.\n")
        self.assert_entry_status(fixture, "supported")


def timing_fixture(*, captured_at="2026-10-15T00:00:00Z", cutoff="regular_delay_1", origin="platform",
                   field_captured_at=None, field_metadata=None):
    """Input: capture/classification/endpoint options. Output: five dicts. Real capture format plus explicit fictional classification."""
    policy = ("In this case, there is a lag of 1 day. This is called Delay 1 simulation. "
              "In expression language, delay is applied automatically and you do not have to bother about it.")
    label = {'regular_delay_1': 'Regular Delay 1', 'fast_d1': 'Fast D1'}.get(cutoff, 'Unknown')
    applicability = ("| Dataset | Field | Instrument type | Region | Delay | Universe | Cutoff class | Timing policy |\n"
                     "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                     f"| d | f | EQUITY | USA | 1 | TOP3000 | {label} | Expression language automatic delay |")
    body = "## How to choose the Simulation Settings\n" + policy + "\n## Field Timing\n" + applicability + "\n"
    first, index, texts = material(body)
    path = first["evidence_ref"]["source_path"]
    # Rebuild real capture metadata and bytes together; compilation time is never evidence.
    index[path]["captured_at"] = captured_at
    texts[path] = render_front_matter({k: v for k, v in index[path].items() if k != "file_sha256"}) + body
    index[path]["file_sha256"] = hashlib.sha256(texts[path].encode()).hexdigest()
    first["evidence_ref"]["capture_date"] = captured_at[:10]
    first["locator"].update(heading="How to choose the Simulation Settings", quote=policy)
    second = copy.deepcopy(first)
    second["locator"].update(heading="Field Timing", quote=applicability)
    field = dict(id="f", dataset=dict(id="d", name="Dataset"), type="MATRIX", region="USA", delay=1,
                 universe="TOP3000", dateCreated="2026-03-01", description="A captured measurement.")
    field.update(field_metadata or {})
    field_captured_at = captured_at if field_captured_at is None else field_captured_at
    payload = dict(data_set=dict(id="d", region="USA", delay=1, universe="TOP3000"), field=field,
                   scope=dict(SCOPE), generated_at=field_captured_at,
                   endpoint="/data-fields" if origin == "platform" else "/external/data-fields")
    raw = json.dumps(payload) + "\n"
    path = "raw/platform/data_fields/fields.jsonl"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    index[path] = dict(path=path, content_hash=digest, file_sha256=digest, captured_at=field_captured_at,
                       source_type="platform_data_field_capture", source_family="raw/platform/data_fields")
    texts[path] = raw
    third = dict(evidence_ref=dict(source_path=path, sha256=digest, capture_date=field_captured_at[:10], kind="documented"),
                 locator=dict(kind="json_value", row_identity=dict(dataset_id="d", field_id="f", scope=dict(SCOPE)),
                              value_path=[], expected_value=payload))
    contract = dict(timing_contract(), rule_version=3, premises=[first, second, third])
    row = dict(field_id="f", dataset_id="d", field_type="MATRIX", **SCOPE)
    scope = dict(SCOPE, as_of="2026-10-15T00:00:00Z")
    return contract, row, scope, index, texts


def replace_timing_capture(fixture, payload):
    """Input: fixture tuple and captured payload dict. Output: None. Rehash changed raw facts, not corrupt bytes."""
    path = "raw/platform/data_fields/fields.jsonl"
    raw = json.dumps(payload) + "\n"
    fixture[4][path] = raw
    digest = hashlib.sha256(raw.encode()).hexdigest()
    fixture[3][path].update(content_hash=digest, file_sha256=digest)
    premise = next(p for p in fixture[0]['premises'] if p['locator']['kind'] == 'json_value')
    premise['evidence_ref']['sha256'] = digest
    premise['locator']['expected_value'] = copy.deepcopy(payload if not premise['locator']['value_path'] else payload['field'])


def replace_timing_document(fixture, position, quote):
    """Input: fixture tuple, premise position int, quote str. Output: None. Rehash complete documented fixture statements."""
    fixture[0]['premises'][position]['locator']['quote'] = quote
    docs = [premise for premise in fixture[0]['premises'] if premise['locator']['kind'] == 'markdown_quote']
    headings = {}
    for premise in docs:
        headings.setdefault(premise['locator']['heading'], []).append(premise['locator']['quote'])
    body = ''.join('## ' + heading + '\n' + '\n'.join(quotes) + '\n' for heading, quotes in headings.items())
    path = fixture[0]['premises'][position]['evidence_ref']['source_path']
    digest = hashlib.sha256(body.encode()).hexdigest()
    fixture[3][path]['content_hash'] = digest
    metadata = {key: value for key, value in fixture[3][path].items() if key != 'file_sha256'}
    text = render_front_matter(metadata) + body
    fixture[4][path] = text
    fixture[3][path]['file_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    for premise in docs:
        premise['evidence_ref']['sha256'] = digest


def named_comparison_fixture():
    """Input: none. Output: five dicts. Use actual July09 prose/cutoffs with a fictional complete captured row."""
    fixture = timing_fixture()
    identity = dict(dataset_id='socialmedia12', field_id='snt_buzz')
    fixture[0]['field_identity'] = dict(identity)
    fixture[1].update(identity)
    payload = json.loads(fixture[4]['raw/platform/data_fields/fields.jsonl'])
    payload['data_set']['id'] = identity['dataset_id']
    payload['field']['id'] = identity['field_id']
    payload['field']['dataset']['id'] = identity['dataset_id']
    fixture[0]['premises'][2]['locator']['row_identity'].update(identity)
    replace_timing_capture(fixture, payload)
    naming = 'Regular D1 Field: snt_buzz Fast D1 Field: snt_buzz_fast_d1'
    timing = ("Delay Field Type Data Timestamp Information Captured 1 snt_buzz Yesterday's market close "
              "Yesterday\u2019s End-of-day data only Fast D1 snt_buzz_fast_d1 Today's market open "
              "Overnight news, events, pre-market moves")
    fixture[0]['premises'][1]['locator'].update(heading='Fast D1 Documentation', quote=naming)
    comparison = copy.deepcopy(fixture[0]['premises'][1])
    comparison['locator']['quote'] = timing
    fixture[0]['premises'].insert(2, comparison)
    replace_timing_document(fixture, 1, naming)
    return fixture


class TimingResolutionTests(unittest.TestCase):
    def test_actual_named_regular_field_and_cutoff_composition(self):
        from wqb.resource_evidence import verify_premise
        fixture = named_comparison_fixture()
        for premise in fixture[0]['premises']:
            verify_premise(premise, fixture[3], fixture[4])
        receipt = self.resolve(fixture)
        self.assertEqual(receipt['status'], 'supported')
        self.assertEqual(receipt['value']['field_identity'], {'dataset_id': 'socialmedia12', 'field_id': 'snt_buzz'})
        self.assertIs(receipt['value']['historical_pit_verified'], False)

    def test_scoped_explicit_facts_do_not_require_an_official_table_schema(self):
        from wqb.resource_evidence import verify_premise
        fixture = timing_fixture()
        prose = ('Field: f; Dataset: d; Universe: TOP3000; Region: USA; Delay: 1; Instrument type: EQUITY; '
                 'Cutoff class: Regular D1; Timing policy: Expression language automatic delay')
        replace_timing_document(fixture, 1, prose)
        self.assertEqual(verify_premise(fixture[0]['premises'][1], fixture[3], fixture[4]), prose)
        self.assertEqual(self.resolve(fixture)['status'], 'supported')

    def test_named_comparison_cannot_classify_an_unlisted_or_fast_field(self):
        for field_id in ('close', 'volume', 'unlisted', 'snt_buzz_fast_d1'):
            fixture = named_comparison_fixture()
            fixture[0]['field_identity']['field_id'] = field_id
            fixture[1]['field_id'] = field_id
            payload = json.loads(fixture[4]['raw/platform/data_fields/fields.jsonl'])
            payload['field']['id'] = field_id
            fixture[0]['premises'][-1]['locator']['row_identity']['field_id'] = field_id
            replace_timing_capture(fixture, payload)
            with self.subTest(field_id=field_id):
                self.unsupported(fixture)

    def test_named_comparison_requires_both_explicit_facts_and_consistent_counterparts(self):
        for position in (1, 2):
            fixture = named_comparison_fixture()
            fixture[0]['premises'].pop(position)
            self.unsupported(fixture)
        for position, old, new in ((1, 'snt_buzz_fast_d1', 'unrelated_fast_d1'),
                                   (2, 'snt_buzz_fast_d1', 'unrelated_fast_d1'),
                                   (2, "Yesterday's market close", "Today's market open"),
                                   (2, 'Yesterday\u2019s End-of-day data only', 'Unknown availability')):
            fixture = named_comparison_fixture()
            quote = fixture[0]['premises'][position]['locator']['quote'].replace(old, new)
            replace_timing_document(fixture, position, quote)
            with self.subTest(position=position, old=old):
                self.unsupported(fixture)
        fixture = named_comparison_fixture()
        fixture[0]['premises'][2]['locator']['heading'] = 'Unrelated article'
        replace_timing_document(fixture, 2, fixture[0]['premises'][2]['locator']['quote'])
        self.unsupported(fixture)

    def test_explicit_key_value_classification_rejects_missing_conflicting_or_unknown_facts(self):
        valid = ('Dataset: d\nField: f\nInstrument type: EQUITY\nRegion: USA\nDelay: 1\nUniverse: TOP3000\n'
                 'Cutoff class: Regular D1\nTiming policy: Expression language automatic delay')
        for quote in (valid.replace('Region: USA\n', ''), valid.replace('Delay: 1', 'Delay: True'),
                      valid.replace('Regular D1', 'Fast D1'), valid + '\nDelay: 0', valid + '\nVerified: true',
                      valid.replace('Dataset: d', 'Dataset: unrelated')):
            fixture = timing_fixture()
            replace_timing_document(fixture, 1, quote)
            self.unsupported(fixture)
        fixture = timing_fixture()
        replace_timing_document(fixture, 1, valid)
        self.assertEqual(self.resolve(fixture)['status'], 'supported')

    def test_documented_classification_must_be_exact_scoped_and_explicit(self):
        for old, new in (('| d |', '| other |'), ('| f |', '| unrelated |'), ('| USA |', '| EUR |'),
                         ('| 1 |', '| True |'), ('| TOP3000 |', '| TOP500 |'),
                         ('Regular Delay 1', 'Fast D1'), ('Expression language automatic delay', 'Unknown')):
            fixture = timing_fixture()
            quote = fixture[0]['premises'][1]['locator']['quote'].replace(old, new)
            replace_timing_document(fixture, 1, quote)
            with self.subTest(old=old):
                self.unsupported(fixture)
        fixture = timing_fixture()
        quote = fixture[0]['premises'][1]['locator']['quote']
        replace_timing_document(fixture, 1, quote + '\n' + quote.splitlines()[-1])
        self.unsupported(fixture)

    def test_implementation_authored_policy_and_name_only_classification_rejected(self):
        fixture = timing_fixture()
        replace_timing_document(fixture, 0, 'For regular Delay 1, the platform automatically delays expression data by one trading day.')
        self.unsupported(fixture)
        fixture = timing_fixture()
        replace_timing_document(fixture, 1, 'Field f has no Fast D1 suffix.')
        self.unsupported(fixture)

    def test_nested_snapshot_scope_cannot_hide_behind_matching_available_tuple(self):
        fixture = timing_fixture()
        fixture[1]['available_scopes'] = [dict(SCOPE, dataset={'region': 'EUR'})]
        self.unsupported(fixture)

    def test_actual_capture_shape_and_official_delay_wording_with_independent_classification(self):
        fixture = timing_fixture()
        raw_field = fixture[0]['premises'][2]['locator']['expected_value']['field']
        self.assertNotIn('origin', raw_field)
        self.assertNotIn('cutoff_class', raw_field)
        self.assertEqual(self.resolve(fixture)['status'], 'supported')
        # Actual policy + actual capture cannot supply a missing classification fact.
        fixture[0]['premises'].pop(1)
        self.unsupported(fixture)

    def test_origin_requires_verified_official_endpoint_not_model_raw_flags(self):
        for endpoint in (None, '', '/uploads', 'https://example.com/data-fields'):
            fixture = timing_fixture()
            payload = json.loads(fixture[4]['raw/platform/data_fields/fields.jsonl'])
            payload['endpoint'] = endpoint
            payload['field'].update(origin='platform', cutoff_class='regular_delay_1')
            replace_timing_capture(fixture, payload)
            self.unsupported(fixture)

    def test_all_nested_captured_scope_facts_must_agree(self):
        for container in ('field', 'data_set', 'field.dataset'):
            for key, value in (('delay', 0), ('delay', True), ('region', 'EUR'),
                               ('universe', 'TOP500'), ('instrument_type', 'FUTURES')):
                with self.subTest(container=container, key=key, value=value):
                    fixture = timing_fixture()
                    payload = json.loads(fixture[4]['raw/platform/data_fields/fields.jsonl'])
                    target = payload['field']['dataset'] if container == 'field.dataset' else payload[container]
                    target[key] = value
                    replace_timing_capture(fixture, payload)
                    self.unsupported(fixture)

    def resolve(self, fixture):
        """Input: fixture tuple. Output: dict. Exercise the public pure resolver without mocks."""
        api = importlib.import_module("wqb.resource_evidence")
        self.assertTrue(hasattr(api, "resolve_timing_contract"), "Task2 resolver missing")
        return api.resolve_timing_contract(*fixture)

    def unsupported(self, fixture):
        """Input: fixture tuple. Output: None. Check fail-closed shape and useful diagnostics."""
        result = self.resolve(fixture)
        self.assertEqual(set(result), {"status", "value", "rejections"})
        self.assertEqual(result["status"], "unsupported")
        self.assertIsNone(result["value"])
        self.assertTrue(result["rejections"])
        self.assertTrue(result["rejections"][0]["message"])

    def test_v2_regular_delay_policy_receipt(self):
        fixture = timing_fixture()
        before = copy.deepcopy(fixture)
        result = self.resolve(fixture)
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["rejections"], [])
        receipt = result["value"]
        self.assertEqual(receipt["rule_id"], "regular_delay_1")
        self.assertEqual(receipt["rule_version"], 3)
        self.assertEqual(receipt["cutoff_class"], "regular_delay_1")
        self.assertIs(receipt["historical_pit_verified"], False)
        self.assertNotIn("available_at", receipt)
        self.assertEqual(receipt["scope"], SCOPE)
        self.assertEqual(receipt["field_identity"], {"dataset_id": "d", "field_id": "f"})
        for key in ("contract_digest", "policy_digest", "rule_digest", "receipt_digest"):
            self.assertRegex(receipt[key], r"^[a-f0-9]{64}$")
        self.assertEqual(len(receipt["sources"]), 2)
        for source in receipt["sources"]:
            self.assertEqual(source["captured_at"], "2026-10-15T00:00:00Z")
            self.assertRegex(source["file_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.resolve(fixture), result)
        self.assertEqual(fixture, before)

    def test_fast_d1_external_or_ambiguous_policy_rejected(self):
        for cutoff, origin in (("fast_d1", "platform"), ("unknown", "platform"),
                               ("regular_delay_1", "external")):
            with self.subTest(cutoff=cutoff, origin=origin):
                self.unsupported(timing_fixture(cutoff=cutoff, origin=origin))
        for count in (0, 1, 2):
            fixture = timing_fixture()
            fixture[0]["premises"] = fixture[0]["premises"][:count]
            self.unsupported(fixture)
        for patch in (dict(cutoff_class="fast_d1"), dict(rule_id="unknown"), dict(rule_version=1)):
            fixture = timing_fixture()
            fixture[0].update(patch)
            self.unsupported(fixture)
        fixture = timing_fixture()
        fixture[0]["premises"][1] = copy.deepcopy(fixture[0]["premises"][0])
        self.unsupported(fixture)

    def test_policy_cannot_override_future_timestamp(self):
        for value in ("2026-10-15T00:00:01Z", "unknown", "", None, True, "2026-10-14T00:00:00"):
            fixture = timing_fixture()
            fixture[1]["available_at"] = value
            with self.subTest(value=value):
                self.unsupported(fixture)
        fixture = timing_fixture()
        fixture[1]["available_at"] = "2026-10-14T00:00:00Z"
        self.assertEqual(self.resolve(fixture)["status"], "supported")

    def test_policy_scope_and_source_age_bound(self):
        self.assertEqual(self.resolve(timing_fixture(captured_at="2026-07-17T00:00:00Z"))["status"], "supported")
        for captured in ("2026-07-16T23:59:59Z", "2026-10-15T00:00:01Z", "2026-10-15T00:00:00"):
            with self.subTest(captured=captured):
                self.unsupported(timing_fixture(captured_at=captured))
        for patch in (dict(delay=True), dict(delay=0), dict(instrument_type="FUTURES"), dict(region="EUR"),
                      dict(universe="OTHER"), dict(as_of="unknown"), dict(as_of=None)):
            fixture = timing_fixture()
            fixture[2].update(patch)
            self.unsupported(fixture)
        fixture = timing_fixture()
        fixture[1]["available_scopes"] = [dict(SCOPE, region="EUR")]
        self.unsupported(fixture)

    def test_timing_source_tampering_wrong_family_and_claimed_trust_rejected(self):
        fixture = timing_fixture()
        for path in fixture[4]:
            changed = copy.deepcopy(fixture)
            changed[4][path] += "tampered"
            self.unsupported(changed)
        for patch in (dict(historical_pit_verified=True), dict(verified=True)):
            changed = timing_fixture()
            changed[0].update(patch)
            self.unsupported(changed)
        fixture = timing_fixture()
        fixture[1]["field_id"] = "other"
        self.unsupported(fixture)
        fixture = timing_fixture()
        fixture[1]["field_type"] = "VECTOR"
        self.unsupported(fixture)
        for source_type, family in (("platform_learn_material", "raw/platform/learn"),
                                    ("platform_activity_snapshot", "raw/platform/activities")):
            fixture = timing_fixture()
            fixture[3]["raw/platform/data_fields/fields.jsonl"].update(source_type=source_type, source_family=family)
            self.unsupported(fixture)
        for patch in ({"origin": None}, {"cutoff_class": None}, {"type": "VECTOR"}):
            self.unsupported(timing_fixture(field_metadata=patch))

    def test_source_scope_alias_is_exact_and_conflicts_reject(self):
        for patch in (dict(sourceScope=dict(SCOPE, delay=True)), dict(sourceScope=dict(SCOPE, extra=1)),
                      dict(scope=dict(SCOPE, region="EUR")), dict(capturedAt="2026-10-14T00:00:00Z")):
            fixture = timing_fixture()
            path = "raw/platform/data_fields/fields.jsonl"
            payload = json.loads(fixture[4][path])
            payload.update(patch)
            raw = json.dumps(payload) + "\n"
            fixture[4][path] = raw
            digest = hashlib.sha256(raw.encode()).hexdigest()
            fixture[3][path].update(content_hash=digest, file_sha256=digest)
            fixture[0]["premises"][2]["evidence_ref"]["sha256"] = digest
            self.unsupported(fixture)

    def test_each_source_age_is_checked_not_compilation_date(self):
        self.unsupported(timing_fixture(field_captured_at="2026-07-16T00:00:00Z"))
        self.unsupported(timing_fixture(captured_at="2026-07-16T00:00:00Z",
                                        field_captured_at="2026-10-15T00:00:00Z"))
        fixture = timing_fixture()
        for source in fixture[3].values():
            source['compiled_at'] = '2099-01-01T00:00:00Z'
        self.assertEqual(self.resolve(fixture)['status'], 'supported')

    def test_captured_timestamp_cannot_be_hidden_or_contradicted(self):
        for value in ('2026-10-16T00:00:00Z', None, 'unknown', '2026-10-14T00:00:00'):
            with self.subTest(value=value):
                self.unsupported(timing_fixture(field_metadata={'available_at': value}))
        fixture = timing_fixture(field_metadata={'available_at': '2026-10-13T00:00:00Z'})
        fixture[1]['available_at'] = '2026-10-14T00:00:00Z'
        self.unsupported(fixture)
        fixture[1]['available_at'] = '2026-10-13T08:00:00+08:00'
        self.assertEqual(self.resolve(fixture)['status'], 'supported')

    def test_receipt_binds_frozen_validation_and_source_bytes(self):
        fixture = timing_fixture()
        original = self.resolve(fixture)['value']
        self.assertEqual(original['validated_as_of'], '2026-10-15T00:00:00Z')
        fixture[2]['as_of'] = '2026-10-16T00:00:00Z'
        changed = self.resolve(fixture)['value']
        self.assertNotEqual(changed['receipt_digest'], original['receipt_digest'])
        fixture = timing_fixture(field_metadata={'description': 'Additional captured fact.'})
        changed = self.resolve(fixture)['value']
        self.assertNotEqual(changed['receipt_digest'], original['receipt_digest'])
        self.assertNotEqual(changed['contract_digest'], original['contract_digest'])

    def test_unrelated_documented_quotes_do_not_prove_applicability(self):
        fixture = timing_fixture()
        first, index, texts = material()
        fixture[3].update(index)
        fixture[4].update(texts)
        fixture[0]['premises'][:2] = [first, copy.deepcopy(first)]
        self.unsupported(fixture)

    def test_all_malformed_resolver_inputs_fail_closed(self):
        for position in range(5):
            fixture = list(timing_fixture())
            fixture[position] = None
            with self.subTest(position=position):
                self.unsupported(fixture)


class ResourceEvidenceTests(unittest.TestCase):
    def api(self):
        """Input: TestCase. Output: module. Fail explicitly when the new public helper is absent."""
        from wqb import semantic_contracts
        self.assertTrue(hasattr(semantic_contracts, "timing_contract_from_dict"), "Task1 parser missing")
        return importlib.import_module("wqb.resource_evidence")

    def test_version_bool_unknown_or_mismatch_rejected(self):
        # Paired envelope/pack mismatch is integrated in Task4, not inferred here.
        api = self.api()
        self.assertEqual(api.resource_contract_version({}), 1)
        for version in (1, 2):
            self.assertEqual(api.resource_contract_version(dict(resource_contract_version=version)), version)
        for version in (True, False, None, "2", 2.0, 0, 3):
            with self.subTest(version=version), self.assertRaises(ValueError):
                api.resource_contract_version(dict(resource_contract_version=version))
        with self.assertRaises(ValueError):
            api.resource_contract_version([])

    def test_premise_hash_locator_identity_and_types(self):
        api = self.api()
        premise, index, texts = material()
        self.assertEqual(api.verify_premise(premise, index, texts), "Exact policy.")
        path = premise["evidence_ref"]["source_path"]
        for key, value in (("path", "raw/platform/learn/wrong.md"), ("content_hash", "b" * 64),
                           ("file_sha256", "b" * 64), ("captured_at", "2026-10-14T00:00:00Z"),
                           ("source_family", "raw/platform/activities"), ("source_type", "platform_api")):
            changed = copy.deepcopy(index)
            changed[path][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.verify_premise(premise, changed, texts)
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, {path: texts[path] + "tampered"})
        for patch in (dict(kind="hypothesis"), dict(verified=True), dict(capture_date="2026-10-14")):
            changed = copy.deepcopy(premise)
            changed["evidence_ref"].update(patch)
            with self.assertRaises(ValueError):
                api.verify_premise(changed, index, texts)
        for body, heading, quote in (("## Timing\nNo.\n## Other\nExact policy.\n", "Timing", "Exact policy."),
                                     ("## Timing\nExact policy.\n## Timing\nExact policy.\n", "Timing", "Exact policy."),
                                     ("```\n## Timing\nExact policy.\n```\n", "Timing", "Exact policy.")):
            changed, idx, txt = material(body)
            changed["locator"].update(heading=heading, quote=quote)
            with self.assertRaises(ValueError):
                api.verify_premise(changed, idx, txt)
        raw = dict(data_set=dict(id="d"), field=dict(id="f", value=1), scope=dict(SCOPE))
        premise, index, texts = material(json.dumps(raw) + "\n", "jsonl")
        premise["locator"] = dict(kind="json_value", row_identity=dict(dataset_id="d", field_id="f", scope=dict(SCOPE)),
                                  value_path=["field", "value"], expected_value=1)
        self.assertEqual(api.verify_premise(premise, index, texts), 1)
        for expected in (True, 1.0, "1"):
            changed = copy.deepcopy(premise)
            changed["locator"]["expected_value"] = expected
            with self.assertRaises(ValueError):
                api.verify_premise(changed, index, texts)
        for patch in (dict(dataset_id="other"), dict(scope=dict(SCOPE, delay=True))):
            changed = copy.deepcopy(premise)
            changed["locator"]["row_identity"].update(patch)
            with self.assertRaises(ValueError):
                api.verify_premise(changed, index, texts)
        duplicate, idx, txt = material((json.dumps(raw) + "\n") * 2, "jsonl")
        duplicate["locator"] = premise["locator"]
        with self.assertRaises(ValueError):
            api.verify_premise(duplicate, idx, txt)

    def test_legacy_optional_fields_omitted(self):
        from wqb.data_ledger import data_ledger_record_from_dict, data_ledger_record_to_dict
        from wqb.operator_semantics import operator_semantic_record_from_dict, operator_semantic_record_to_dict
        for load, dump, key in ((data_ledger_record_from_dict, data_ledger_record_to_dict, "timing_contract"),
                                (operator_semantic_record_from_dict, operator_semantic_record_to_dict, "definition_basis")):
            row = dump(load({}))
            self.assertNotIn(key, row)
            self.assertEqual(dump(load(row)), row)

    def test_optional_contract_roundtrip(self):
        from wqb.data_ledger import data_ledger_record_from_dict, data_ledger_record_to_dict
        from wqb.operator_semantics import operator_semantic_record_from_dict, operator_semantic_record_to_dict
        for load, dump, key, value in ((data_ledger_record_from_dict, data_ledger_record_to_dict, "timing_contract", timing_contract()),
                                       (operator_semantic_record_from_dict, operator_semantic_record_to_dict, "definition_basis", definition_basis())):
            row = dump(load({key: value}))
            self.assertEqual(row.get(key), value)
            self.assertEqual(dump(load(row)), row)
            for malformed in (None, dict(value, verified=True)):
                with self.assertRaises(ValueError):
                    load({key: malformed})
            with self.assertRaises(ValueError):
                load({key: value, "unknown_contract": True})

    def test_strict_shapes_and_bounds(self):
        self.api()
        from wqb.resource_evidence import MAX_PREMISES, MAX_QUOTE_BYTES, verify_premise
        from wqb.semantic_contracts import timing_contract_from_dict, definition_basis_from_dict
        for parser, value in ((timing_contract_from_dict, timing_contract()), (definition_basis_from_dict, definition_basis())):
            self.assertEqual(parser(value), value)
            for patch in (dict(rule_version=True), dict(rule_version=0), dict(unknown=1)):
                with self.assertRaises(ValueError):
                    parser(dict(value, **patch))
        for patch in (dict(historical_pit_verified=True), dict(historical_pit_verified=0),
                      dict(scope=dict(SCOPE, delay=True)), dict(field_identity=dict(field_id="f")),
                      dict(premises=[]), dict(premises=[material()[0]] * (MAX_PREMISES + 1))):
            with self.assertRaises(ValueError):
                timing_contract_from_dict(dict(timing_contract(), **patch))
        premise, index, texts = material()
        for patch in (dict(quote="x" * (MAX_QUOTE_BYTES + 1)), dict(verified=True), dict(kind="eval")):
            changed = copy.deepcopy(premise)
            changed["locator"].update(patch)
            with self.assertRaises(ValueError):
                verify_premise(changed, index, texts)


    def test_optional_source_identity_metadata_cannot_conflict(self):
        api = self.api()
        premise, index, texts = material()
        path = premise["evidence_ref"]["source_path"]
        index[path]["source_path"] = "raw/platform/learn/other.md"
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, texts)
        premise, index, texts = material()
        row = index[path]
        row["scope"] = dict(SCOPE)
        metadata = dict(row, scope="different-scope")
        metadata.pop("file_sha256")
        texts[path] = render_front_matter(metadata) + "## Timing\nExact policy.\n"
        row["content_hash"] = hashlib.sha256(b"## Timing\nExact policy.\n").hexdigest()
        premise["evidence_ref"]["sha256"] = row["content_hash"]
        texts[path] = texts[path].replace(metadata["content_hash"], row["content_hash"])
        row["file_sha256"] = hashlib.sha256(texts[path].encode()).hexdigest()
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, texts)

    def test_full_bytes_lf_only_and_optional_hashes(self):
        api = self.api()
        premise, index, texts = material("## Timing\nExact policy.\n" + "Long complete source.\n" * 1000)
        path = premise["evidence_ref"]["source_path"]
        raw = texts[path].replace("\n", "\r\n").encode()
        index[path]["file_sha256"] = hashlib.sha256(raw).hexdigest()
        self.assertEqual(api.verify_premise(premise, index, {path: raw}), "Exact policy.")
        self.assertEqual(api.verify_premise(premise, index, {path: raw.decode()}), "Exact policy.")
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, {path: raw[:500]})
        for replacement in ("Exact  policy.", "Exact\tpolicy."):
            changed = copy.deepcopy(premise)
            changed["locator"]["quote"] = replacement
            with self.assertRaises(ValueError):
                api.verify_premise(changed, index, {path: raw})
        index[path].pop("file_sha256")
        self.assertEqual(api.verify_premise(premise, index, {path: raw}), "Exact policy.")
        for key, value in (("source_path", "raw/platform/learn/other.md"), ("file_sha256", "b" * 64),
                           ("content_hash", "b" * 64), ("source_type", "platform_api")):
            body = "## Timing\nExact policy.\n"
            p, idx, txt = material(body)
            metadata = dict(idx[path])
            metadata.pop("file_sha256")
            metadata[key] = value
            txt[path] = render_front_matter(metadata) + body
            idx[path]["file_sha256"] = hashlib.sha256(txt[path].encode()).hexdigest()
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.verify_premise(p, idx, txt)

    def test_json_full_document_literal_paths_and_duplicate_keys(self):
        api = self.api()
        row = dict(dataset_id="d", field_id="f", scope=dict(SCOPE), fact=dict(items=[True, None, 1]))
        locator = dict(kind="json_value", row_identity=dict(dataset_id="d", field_id="f", scope=dict(SCOPE)),
                       value_path=["fact"], expected_value=row["fact"])
        for payload in (row, [row], dict(rows=[row]), dict(results=[row]), dict(data_fields=[row])):
            premise, index, texts = material(json.dumps(payload), "json")
            premise["locator"] = copy.deepcopy(locator)
            self.assertEqual(api.verify_premise(premise, index, texts), row["fact"])
            premise["locator"]["expected_value"]["items"][0] = 1
            with self.assertRaises(ValueError):
                api.verify_premise(premise, index, texts)
        for body in (json.dumps(row).replace('"dataset_id": "d"', '"dataset_id": "d", "dataset_id": "d"'),
                     json.dumps([row, row])):
            premise, index, texts = material(body, "json")
            premise["locator"] = locator
            with self.assertRaises(ValueError):
                api.verify_premise(premise, index, texts)
        premise, index, texts = material(json.dumps(row), "json")
        premise["locator"] = dict(locator, value_path=["fact.items[0]"])
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, texts)
        premise["locator"] = locator
        index[premise["evidence_ref"]["source_path"]]["scope"] = dict(SCOPE, delay=0)
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, texts)

    def test_markdown_heading_identity_does_not_strip_literal_hash(self):
        api = self.api()
        premise, index, texts = material("## Timing#\nExact policy.\n")
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, texts)
        premise["locator"]["heading"] = "Timing#"
        self.assertEqual(api.verify_premise(premise, index, texts), "Exact policy.")
        premise, index, texts = material("## Timing ##\nExact policy.\n")
        self.assertEqual(api.verify_premise(premise, index, texts), "Exact policy.")

    def test_duplicate_frontmatter_keys_reject_before_last_wins_parse(self):
        """Input: duplicate header keys. Output: None. Reject conflicting and identical ambiguity."""
        api = self.api()
        for key, first in (("source_type", "platform_api"), ("captured_at", "2000-01-01T00:00:00Z"),
                           ("capture_tool", "other"), ("source_type", "platform_learn_material")):
            premise, index, texts = material()
            path = premise["evidence_ref"]["source_path"]
            texts[path] = texts[path].replace("---\n", "---\n" + key + ": " + first + "\n", 1)
            if key == "capture_tool":
                texts[path] = texts[path].replace("---\n", "---\ncapture_tool: original\n", 1)
            index[path]["file_sha256"] = hashlib.sha256(texts[path].encode()).hexdigest()
            with self.subTest(key=key, first=first), self.assertRaises(ValueError):
                api.verify_premise(premise, index, texts)

    def test_partial_mixed_json_identity_aliases_reject_conflicts(self):
        """Input: mixed canonical/capture aliases. Output: None. Check every supplied identity alias."""
        api = self.api()
        for alias in (dict(data_set=dict(id="OTHER")), dict(field=dict(id="OTHER")),
                      dict(data_set="d"), dict(field=dict()),
                      dict(data_set=dict(id=True))):
            row = dict(dataset_id="d", field_id="f", scope=dict(SCOPE), fact=1, **alias)
            for suffix in ("json", "jsonl"):
                premise, index, texts = material(json.dumps(row), suffix)
                premise["locator"] = dict(kind="json_value", row_identity=dict(dataset_id="d", field_id="f", scope=dict(SCOPE)),
                                           value_path=["fact"], expected_value=1)
                with self.subTest(alias=alias, suffix=suffix), self.assertRaises(ValueError):
                    api.verify_premise(premise, index, texts)
        for aliases in (dict(data_set=dict(id="d")), dict(field=dict(id="f")),
                        dict(data_set=dict(id="d"), field=dict(id="f"))):
            row = dict(dataset_id="d", field_id="f", scope=dict(SCOPE), fact=1, **aliases)
            premise, index, texts = material(json.dumps(row), "json")
            premise["locator"] = dict(kind="json_value", row_identity=dict(dataset_id="d", field_id="f", scope=dict(SCOPE)),
                                       value_path=["fact"], expected_value=1)
            self.assertEqual(api.verify_premise(premise, index, texts), 1)

    def test_html_comments_cannot_supply_headings_or_quotes(self):
        """Input: hidden headings/quotes and visible code examples. Output: None. Exclude only actual comments."""
        api = self.api()
        for body in ("<!--\n## Timing\nExact policy.\n-->\n",
                     "## Timing\n<!-- Exact policy. -->\n",
                     "## Timing\nEx<!-- hidden -->act policy.\n"):
            premise, index, texts = material(body)
            with self.subTest(body=body), self.assertRaises(ValueError):
                api.verify_premise(premise, index, texts)
        for body, quote in (("<!--\n## Timing\nHidden.\n-->\n## Timing\nExact policy.\n", "Exact policy."),
                            ("## Timing\n<!-- Exact policy. -->\nExact policy.\n", "Exact policy."),
                            ("## Timing\n```html\n<!-- Exact policy. -->\n```\n", "<!-- Exact policy. -->"),
                            ("## Timing\n`<!-- Exact policy. -->`\n", "<!-- Exact policy. -->"),
                            ("## Timing\n`` ` <!-- Exact policy. --> ``\n", "<!-- Exact policy. -->"),
                            ("## Timing\n```html\n\\`\n<!-- Exact policy. -->\n`\n```\n", "Exact policy."),
                            ("## Timing\n~~~html\n\\<!-- Exact policy. -->\n~~~\n", "Exact policy."),
                            ("```html\n<!--\n```\n## Timing\nExact policy.\n", "Exact policy.")):
            premise, index, texts = material(body)
            premise["locator"]["quote"] = quote
            with self.subTest(body=body):
                self.assertEqual(api.verify_premise(premise, index, texts), quote)
        premise, index, texts = material("## Timing\nUnmatched ` <!-- Exact policy. -->\n")
        with self.assertRaises(ValueError):
            api.verify_premise(premise, index, texts)

    def test_malformed_frontmatter_structure_raises_valueerror(self):
        """Input: malformed header structure. Output: None. Reject locally before legacy parser crashes."""
        api = self.api()
        for line in ("source_type: platform_learn_material\n  - bad\n", "  nested: bad\n",
                     "- orphan\n", "source_type:\n    nested: bad\n",
                     "source_type:\n# comment: scalar\n  - bad\n"):
            premise, index, texts = material()
            path = premise["evidence_ref"]["source_path"]
            texts[path] = texts[path].replace("source_type: platform_learn_material\n", line)
            index[path]["file_sha256"] = hashlib.sha256(texts[path].encode()).hexdigest()
            with self.subTest(line=line), self.assertRaises(ValueError):
                api.verify_premise(premise, index, texts)
        premise, index, texts = material()
        path = premise["evidence_ref"]["source_path"]
        texts[path] = texts[path].replace("---\n", "---\ncompiled_targets:\n  - wiki/20_data_semantics.md\n", 1)
        index[path]["file_sha256"] = hashlib.sha256(texts[path].encode()).hexdigest()
        self.assertEqual(api.verify_premise(premise, index, texts), "Exact policy.")

    def test_field_nested_dataset_alias_must_match_resolved_dataset(self):
        """Input: field.dataset aliases in actual capture wrappers. Output: None. Reject conflicts, preserve matching IDs."""
        api = self.api()
        for suffix in ("json", "jsonl"):
            for dataset in (dict(id="OTHER"), dict(id=True), dict(), "d", dict(id="d")):
                row = dict(data_set=dict(id="d"), field=dict(id="f", dataset=dataset, fact=1), scope=dict(SCOPE))
                premise, index, texts = material(json.dumps(row), suffix)
                premise["locator"] = dict(kind="json_value", row_identity=dict(dataset_id="d", field_id="f", scope=dict(SCOPE)),
                                           value_path=["field", "fact"], expected_value=1)
                with self.subTest(suffix=suffix, dataset=dataset):
                    if dataset == dict(id="d"):
                        self.assertEqual(api.verify_premise(premise, index, texts), 1)
                    else:
                        with self.assertRaises(ValueError):
                            api.verify_premise(premise, index, texts)

    def test_complex_comment_code_is_explicitly_unsupported(self):
        """Input: escaped/multiline code with comment markers. Output: None. Fail closed, never expose hidden facts."""
        api = self.api()
        bodies = (
            "## Timing\n\\` <!-- Exact policy. --> `\n",
            "## Timing\n\\`` <!-- Exact policy. --> ``\n",
            "## Timing\n`\n<!-- Exact policy. -->\n`\n",
            "## Timing\n``\n<!-- Exact policy. -->\n``\n",
            "## Timing\n\\<!-- Exact policy. -->\n",
            "## Timing\n`text \\` <!-- Exact policy. -->\n",
        )
        for body in bodies:
            premise, index, texts = material(body)
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "unsupported Markdown"):
                api.verify_premise(premise, index, texts)


if __name__ == "__main__":
    unittest.main()
