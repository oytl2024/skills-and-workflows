"""Offline run-local exploration permission is not global reviewed publication."""

from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest

from tests.test_hypothesis_design import compiler_fixture
from wqb import exploration_eligibility as eligibility
from wqb.exploration_eligibility import (
    validate_exploration, verify_exploration, freeze_exploration, match_exploration,
    build_exploration_snapshot,
)


class ExplorationEligibilityTests(unittest.TestCase):
    def test_explicit_snapshot_can_use_existing_paired_selector_without_review_forgery(self):
        from wqb.hypothesis_selection import validate_operational_resource_context, select_experiment_batch
        receipt = validate_exploration(*compiler_fixture(treatment=True))
        snapshot = build_exploration_snapshot([receipt])
        context = validate_operational_resource_context(snapshot)
        result = select_experiment_batch(snapshot, context['experiments'], 8)
        self.assertEqual(len(result['selected']), 2)
        self.assertTrue(all(row['semantic_status'] == 'unreviewed' for row in snapshot['template_rows']))
        snapshot['template_rows'][0]['skeleton'] = 'invented'
        with self.assertRaises(ValueError):
            validate_operational_resource_context(snapshot)

    def test_exploration_requires_explicit_policy_and_receipt(self):
        from wqb.hypothesis_selection import validate_operational_resource_context
        receipt = validate_exploration(*compiler_fixture(treatment=True))
        snapshot = build_exploration_snapshot([receipt])
        for changed in ('policy', 'context'):
            altered = deepcopy(snapshot)
            if changed == 'policy':
                altered['research_policy']['exploration_scout'] = False
            else:
                altered.pop('exploration_context')
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_operational_resource_context(altered)

    def test_compiler_backed_permission_preserves_unreviewed_status(self):
        design, resources, scope = compiler_fixture(treatment=True)
        before = deepcopy((design, resources, scope))
        receipt = validate_exploration(design, resources, scope)
        self.assertEqual(receipt['status'], 'exploration_eligible')
        self.assertEqual(receipt['knowledge_status'], 'exploratory')
        self.assertEqual(len(receipt['compiled']['experiment']['arms']), 2)
        self.assertTrue(all(row['semantic_status'] == 'unreviewed'
                            for row in receipt['compiled']['drafts']))
        self.assertEqual(verify_exploration(receipt), receipt)
        self.assertEqual((design, resources, scope), before)

    def test_tampering_and_invented_authority_fail(self):
        receipt = validate_exploration(*compiler_fixture(treatment=True))
        for change in ('source', 'expression', 'review', 'authority'):
            edited = deepcopy(receipt)
            if change == 'source':
                path = next(iter(edited['compiler_input']['resources']['source_texts']))
                edited['compiler_input']['resources']['source_texts'][path] += 'altered'
            elif change == 'expression':
                edited['compiled']['experiment']['arms'][0]['binding']['bound_expression'] = 'invented'
            elif change == 'review':
                edited['compiled']['drafts'][0]['semantic_status'] = 'reviewed'
            else:
                edited['submit_authorized'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_exploration(edited)

    def test_absent_operator_and_bad_field_are_rejected(self):
        design, resources, scope = compiler_fixture(treatment=True)
        with self.assertRaises(ValueError):
            validate_exploration(design, dict(resources, operator_rows=[]), scope)
        resources['field_rows'][0]['field_type'] = 'VECTOR'
        with self.assertRaises(ValueError):
            validate_exploration(design, resources, scope)

    def test_exact_pair_required_and_matching_is_not_narrative_inference(self):
        with self.assertRaises(ValueError):
            validate_exploration(*compiler_fixture())
        receipt = validate_exploration(*compiler_fixture(treatment=True))
        design = receipt['compiler_input']['design']
        resources = receipt['compiler_input']['resources']
        self.assertEqual(match_exploration([receipt], design, receipt['compiler_input']['scope'], resources), receipt)
        other = deepcopy(design)
        other['mechanism_family'] = 'other_mechanism'
        self.assertIsNone(match_exploration([receipt], other, receipt['compiler_input']['scope'], resources))
        changed = deepcopy(resources)
        changed['settings']['decay'] = 9
        self.assertIsNone(match_exploration([receipt], design, receipt['compiler_input']['scope'], changed))

    def test_mixed_context_cannot_bypass_reviewed_release_verification(self):
        from wqb.hypothesis_selection import validate_operational_resource_context
        snapshot = build_exploration_snapshot([validate_exploration(*compiler_fixture(treatment=True))])
        for key in ('semantic_release', 'operational_resource_context'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_operational_resource_context(dict(snapshot, **{key: {}}))

    def test_bare_fixture_run_cannot_freeze_operational_eligibility(self):
        receipt = validate_exploration(*compiler_fixture(treatment=True))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                freeze_exploration(root, receipt)


class ExplorationCertificationTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; create a temporary indexed vault and opted-in owning run."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vault = self.root / 'knowledge'
        self.run = self.root / 'new-run'
        self.run.mkdir()
        self.design, self.resources, self.scope = compiler_fixture(treatment=True)
        for path, text in self.resources['source_texts'].items():
            target = self.vault / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        self.index = self.vault / 'machine/source_index.jsonl'
        self.index.parent.mkdir(parents=True)
        self.write_index(list(self.resources['source_index'].values()))
        self.manifest = dict(run_id=self.run.name, knowledge_root=str(self.vault),
            selected_scope=self.scope, start_snapshot=dict(selected_scope=self.scope,
                research_policy=dict(exploration_scout=True, paired_scout=True,
                                     exploration_policy_version=1)))
        self.write_manifest()

    def write_index(self, rows):
        """Input: index dict list. Output: None; write only the isolated canonical fixture index."""
        self.index.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

    def write_manifest(self):
        """Input: None. Output: None; save this fixture's explicit frozen Start contract."""
        (self.run / 'run_manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def certify(self):
        """Input: None. Output: certificate dict; invoke resource-only producer before compiling outcome."""
        return eligibility.certify_exploration_resources(self.run, self.vault, self.resources, self.scope)

    def attach(self, receipt, certificate):
        """Input: receipt/certificate dicts. Output: dict; exercise live IO attachment boundary offline."""
        return eligibility.validate_exploration_attachment(self.run, self.vault, receipt, certificate)

    def test_resource_certificate_precedes_outcome_and_freeze_is_immutable(self):
        cert = self.certify()
        self.assertEqual(cert, self.certify())
        self.assertEqual(cert['owning_run']['run_id'], self.run.name)
        self.assertEqual(set(cert['sources']), set(self.resources['source_index']))
        for source in cert['sources'].values():
            self.assertRegex(source['file_sha256'], r'^[0-9a-f]{64}$')
        receipt = validate_exploration(self.design, self.resources, self.scope)
        self.assertEqual(self.attach(receipt, cert), receipt)
        path = freeze_exploration(self.run, receipt, knowledge_root=self.vault, certificate=cert)
        before = path.read_bytes()
        self.assertEqual(freeze_exploration(self.run, receipt, knowledge_root=self.vault, certificate=cert), path)
        self.assertEqual(path.read_bytes(), before)
        path.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            freeze_exploration(self.run, receipt, knowledge_root=self.vault, certificate=cert)

    def test_no_certificate_or_bare_old_run_cannot_attach(self):
        receipt = validate_exploration(self.design, self.resources, self.scope)
        with self.assertRaises(ValueError):
            freeze_exploration(self.run, receipt)
        for change in ('old', 'disabled', 'missing_opt_in', 'versionless', 'coerced_version', 'unpaired'):
            altered = deepcopy(self.manifest)
            policy = altered['start_snapshot']['research_policy']
            if change == 'old':
                altered.pop('start_snapshot')
            elif change == 'disabled':
                policy['exploration_scout'] = False
            elif change == 'missing_opt_in':
                policy.pop('exploration_scout')
            elif change == 'versionless':
                policy.pop('exploration_policy_version')
            elif change == 'coerced_version':
                policy['exploration_policy_version'] = True
            else:
                policy['paired_scout'] = False
            (self.run / 'run_manifest.json').write_text(json.dumps(altered), encoding='utf-8')
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.certify()

    def test_unregistered_or_different_requested_index_is_rejected(self):
        rows = list(self.resources['source_index'].values())
        for changed in (rows[:-1], [dict(row, captured_at='2026-10-15T00:00:00Z') for row in rows], rows + rows):
            self.write_index(changed)
            with self.subTest(rows=changed), self.assertRaises(ValueError):
                self.certify()

    def test_registered_source_metadata_is_not_compared_with_boolean_coercion(self):
        rows = deepcopy(list(self.resources['source_index'].values()))
        rows[0]['record_count'] = 1
        self.write_index(rows)
        self.resources['source_index'][rows[0]['path']]['record_count'] = True
        with self.assertRaises(ValueError):
            self.certify()

    def test_attachment_rechecks_raw_index_manifest_certificate_and_receipt(self):
        cert = self.certify()
        receipt = validate_exploration(self.design, self.resources, self.scope)
        raw = self.vault / next(iter(self.resources['source_texts']))
        certificate_file = self.run / 'runtime/exploration/resources' / (cert['content_sha256'] + '.json')
        for target in (raw, self.index, self.run / 'run_manifest.json', certificate_file):
            before = target.read_bytes()
            if target == certificate_file:
                changed = json.loads(before)
                changed['resources_sha256'] = '0' * 64
                target.write_text(json.dumps(changed), encoding='utf-8')
            elif target.name == 'run_manifest.json':
                changed = json.loads(before)
                changed['start_snapshot']['research_policy']['exploration_policy_version'] = 2
                target.write_text(json.dumps(changed), encoding='utf-8')
            else:
                target.write_bytes(before + b' ')
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.attach(receipt, cert)
            target.write_bytes(before)
        corrupt = deepcopy(cert)
        corrupt['scope']['universe'] = 'OTHER'
        with self.assertRaises(ValueError):
            self.attach(receipt, corrupt)
        corrupt_receipt = deepcopy(receipt)
        corrupt_receipt['compiled']['drafts'][0]['semantic_status'] = 'reviewed'
        with self.assertRaises(ValueError):
            self.attach(corrupt_receipt, cert)
        changed = deepcopy(self.resources)
        changed['settings']['decay'] = 9
        with self.assertRaises(ValueError):
            self.attach(validate_exploration(self.design, changed, self.scope), cert)
        certificate_file.unlink()
        with self.assertRaises(ValueError):
            self.attach(receipt, cert)

    def test_pure_frozen_certificate_does_not_replace_operational_io(self):
        cert = self.certify()
        receipt = validate_exploration(self.design, self.resources, self.scope)
        snapshot = build_exploration_snapshot([receipt], resource_certificates=[cert])
        eligibility.validate_exploration_snapshot(snapshot)
        (self.vault / next(iter(self.resources['source_texts']))).unlink()
        eligibility.validate_exploration_snapshot(snapshot)
        with self.assertRaises((ValueError, OSError)):
            self.attach(receipt, cert)
        changed = deepcopy(snapshot)
        changed['exploration_context']['resource_certificates'][0]['scope']['universe'] = 'OTHER'
        with self.assertRaises(ValueError):
            eligibility.validate_exploration_snapshot(changed)

    def test_certificate_cannot_transfer_runs_or_accept_changed_frozen_policy(self):
        cert = self.certify()
        receipt = validate_exploration(self.design, self.resources, self.scope)
        other = self.root / 'other-run'
        other.mkdir()
        manifest = deepcopy(self.manifest)
        manifest['run_id'] = other.name
        (other / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(ValueError):
            eligibility.validate_exploration_attachment(other, self.vault, receipt, cert)
        self.manifest['start_snapshot']['research_policy']['exploration_scout'] = False
        self.write_manifest()
        with self.assertRaises(ValueError):
            self.attach(receipt, cert)

    def test_supplied_self_consistent_sources_are_not_independent_raw_certification(self):
        receipt = validate_exploration(self.design, self.resources, self.scope)
        (self.vault / next(iter(self.resources['source_texts']))).write_text('different raw', encoding='utf-8')
        self.assertEqual(verify_exploration(receipt), receipt)
        with self.assertRaises(ValueError):
            self.certify()

    def test_frozen_certificate_policy_cannot_be_rewritten_in_snapshot(self):
        cert = self.certify()
        receipt = validate_exploration(self.design, self.resources, self.scope)
        snapshot = build_exploration_snapshot([receipt], resource_certificates=[cert])
        self.assertEqual(snapshot['research_policy'], cert['policy'])
        snapshot['research_policy']['exploration_policy_version'] = 2
        with self.assertRaises(ValueError):
            eligibility.validate_exploration_snapshot(snapshot)

    def test_parent_can_attach_snapshot_without_replacing_frozen_start_authority(self):
        cert = self.certify()
        receipt = validate_exploration(self.design, self.resources, self.scope)
        self.manifest['start_snapshot'] = build_exploration_snapshot([receipt], resource_certificates=[cert])
        self.write_manifest()
        self.assertEqual(self.attach(receipt, cert), receipt)

    def test_saved_certificate_and_receipt_do_not_coerce_boolean_versions(self):
        cert = self.certify()
        receipt = validate_exploration(self.design, self.resources, self.scope)
        path = freeze_exploration(self.run, receipt, knowledge_root=self.vault, certificate=cert)
        certificate_file = self.run / 'runtime/exploration/resources' / (cert['content_sha256'] + '.json')
        for target in (certificate_file, path):
            before = target.read_bytes()
            changed = json.loads(before)
            changed['schema_version'] = True
            target.write_text(json.dumps(changed), encoding='utf-8')
            with self.subTest(target=target), self.assertRaises(ValueError):
                freeze_exploration(self.run, receipt, knowledge_root=self.vault, certificate=cert)
            target.write_bytes(before)

    def test_real_extract_original_and_receipt_are_independently_checked(self):
        from tests.test_knowledge_contracts import FieldSourceExtractionTests
        fixture = FieldSourceExtractionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        result = fixture.extract()
        self.vault = fixture.root
        self.index = self.vault / 'machine/source_index.jsonl'
        rows = [json.loads(line) for line in self.index.read_text(encoding='utf-8').splitlines()]
        excerpt = result['excerpt_path']
        for path, text in self.resources['source_texts'].items():
            target = self.vault / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        self.write_index(rows + list(self.resources['source_index'].values()))
        self.resources['source_index'].update({row['path']: row for row in rows if row['path'] == excerpt})
        self.resources['source_texts'][excerpt] = (self.vault / excerpt).read_text(encoding='utf-8')
        self.manifest['knowledge_root'] = str(self.vault)
        self.write_manifest()
        self.certify()
        targets = [self.vault / fixture.source, self.vault / result['receipt_path']]
        for target in targets:
            before = target.read_bytes()
            if target.suffix == '.json':
                changed = json.loads(before)
                changed['excerpt_sha256'] = '0' * 64
                target.write_text(json.dumps(changed), encoding='utf-8')
            else:
                target.write_bytes(before + b' ')
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.certify()
            target.write_bytes(before)

    def test_repaired_source_requires_the_original_repair_evidence(self):
        from tests.test_knowledge_contracts import SourceMetadataRepairTests
        fixture = SourceMetadataRepairTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.repair(dry_run=False)
        self.vault = fixture.root
        self.index = self.vault / 'machine/source_index.jsonl'
        rows = [json.loads(line) for line in self.index.read_text(encoding='utf-8').splitlines()]
        self.resources = dict(source_index={row['path']: row for row in rows},
            source_texts={fixture.source: (self.vault / fixture.source).read_bytes().decode('utf-8')})
        self.manifest['knowledge_root'] = str(self.vault)
        self.write_manifest()
        self.certify()
        original_cache = fixture.cache / 'operators.json'
        original_cache.write_text('[]', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.certify()


if __name__ == '__main__':
    unittest.main()
