"""Discovery uses the existing durable batch/recovery services, not a second controller."""

import json
import re
import requests
from pathlib import Path

from wqb.recorder import RunRecorder
from wqb.repair_runtime import RepairRecoveryPending, RepairRateLimited, recover_parent_settings
from wqb.rate_limit_state import check_source_retry_authorization, RateLimitRecoveryRequired
from wqb.research_planning import prepare_source_plan
from wqb.stage_outcomes import checked_research_rows
from wqb.runtime_control import check_submission_allowed, utc_now


class DiscoveryRuntimeExecutor:
    def __init__(self, config: dict) -> None:
        """Input: scoped config dict. Output: executor. Reuse managed submission guards and source queues."""
        self.config = dict(config)

    def recover_checks(self, root: Path) -> dict:
        """Input: authorized active run Path. Output: receipt dict. Recover existing checks, never simulate or discover data."""
        from wqb import cli
        from wqb.pending_check_recovery import recover_pending_checks, CHECK_RECOVERY_RECEIPT
        from wqb.runtime_control import _write
        source = root / 'stages/backtest/checks'
        source.mkdir(parents=True, exist_ok=True)
        check_submission_allowed()
        try:
            client = cli.build_client({**self.config, 'max_retries': 0, 'request_timeout_seconds': 20})
            def fetch(identity):
                """Input: existing Alpha ID str. Output: CheckSummary. Observe Pause before each bounded check."""
                check_submission_allowed()
                check_source_retry_authorization(source)
                summary = cli.fetch_check_summary(client, identity)
                from wqb.rate_limit_state import reset_rate_limit
                reset_rate_limit(source, 'existing_alpha_check_completed', utc_now())
                return summary
            return recover_pending_checks(root, fetch)
        except (RateLimitRecoveryRequired, requests.exceptions.RequestException) as exc:
            if isinstance(exc, RateLimitRecoveryRequired):
                retry_at = exc.retry_at
            elif getattr(getattr(exc, 'response', None), 'status_code', 0) == 429:
                from wqb.rate_limit_state import record_rate_limit
                state = record_rate_limit(source, 'check_recovery', exc, {}, utc_now())
                retry_at = str(state['retry_at'])
            else:
                raise RepairRecoveryPending('existing Alpha checks need network recovery; no simulation resubmitted') from exc
            path = root / CHECK_RECOVERY_RECEIPT
            saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            _write(path, {**saved, 'status': 'paused', 'recovery_eligible': True,
                          'rate_limit_retry_at': retry_at, 'rate_limit_source_run_dir': str(source)})
            raise RepairRateLimited(retry_at, str(source)) from exc

    def __call__(self, root: Path, parent: dict) -> list[dict]:
        """Input: active run Path and immutable seed row. Output: checked Discovery children with lineage."""
        from wqb import cli
        source = root / 'stages/batch_generation/source'
        recorder = RunRecorder(source)
        config = {**self.config, 'max_alphas_per_round': 30, 'allow_live_source_fallback': False}
        manifest = json.loads((root / 'run_manifest.json').read_text(encoding='utf-8'))
        config.update({key: manifest['selected_scope'][key] for key in ('region', 'delay', 'universe')})
        schedule = json.loads((root / 'stages/schedule/research_schedule.json').read_text(encoding='utf-8'))
        selected = schedule['template_matches'][0]
        try:
            existing_plan = recorder.read_jsonl('planned_candidates.jsonl')
            existing_rows = checked_research_rows(source)
            checked_hashes = {row['expression_hash'] for row in existing_rows}
            already_complete = 0 < len(existing_plan) <= 30 and all(
                row['expression_hash'] in checked_hashes for row in existing_plan)
            if existing_plan and not already_complete:
                cli.complete_in_flight(config, str(source))
                cli.retry_planned(config, str(source), submit_mode='multi')
            elif not existing_plan:
                check_submission_allowed()
                check_source_retry_authorization(source)
                cli.require_readiness_gate(**cli._live_gate_kwargs(config, source))
                client = cli.build_client({**config, 'max_retries': 0, 'request_timeout_seconds': 20})
                client.authenticate()
                if not parent.get('settings'):
                    parent = recover_parent_settings(root, parent, client)
                for key, platform in [('region', 'region'), ('delay', 'delay'), ('universe', 'universe')]:
                    if parent['settings'].get(platform) != config.get(key):
                        raise ValueError('Discovery seed settings differ from selected scope')
                for key, platform in [('instrument_type', 'instrumentType'), ('decay', 'decay'),
                    ('neutralization', 'neutralization'), ('truncation', 'truncation'),
                    ('pasteurization', 'pasteurization'), ('unit_handling', 'unitHandling'),
                    ('nan_handling', 'nanHandling'), ('language', 'language')]:
                    if platform not in parent['settings']:
                        raise ValueError('Discovery seed settings are incomplete: ' + platform)
                    config[key] = parent['settings'][platform]
                v2 = manifest.get('start_snapshot', {}).get('hypothesis_binding_version') == 2
                if v2:
                    metadata = dict(workflow_stage='discovery', measured_seed=parent,
                        research_round_id=schedule.get('research_round_id', 'round-0001') + '-discovery')
                else:
                    field = selected['field_id']
                    skeleton = parent['expression'].replace(f'vec_avg({field})', '{field}')
                    skeleton = re.sub(r'\b' + re.escape(field) + r'\b', '{field}', skeleton)
                    if '{field}' not in skeleton:
                        raise ValueError('Discovery seed does not use scheduled field')
                    seed_template = {**selected, 'skeleton': skeleton, 'seed_expression': parent['expression']}
                    metadata = {'research_round_id': schedule.get('research_round_id', 'round-0001') + '-discovery',
                                'exact_field_id': field, 'template_provenance': seed_template,
                                'parent_expression_hash': parent['expression_hash']}
                config.update(prepare_source_plan(root, config, metadata, utc_now()))
                cli.run_field_batch(client, recorder, config, field_search='' if v2 else selected['field_id'],
                    dataset_id='' if v2 else selected['dataset_id'], exact_field_id='' if v2 else selected['field_id'],
                    template_mode='economic', workflow_stage='discovery', submit_mode='multi')
            planned = recorder.read_jsonl('planned_candidates.jsonl')
            rows = checked_research_rows(source)
            checked = {row['expression_hash'] for row in rows}
            if not 0 < len(planned) <= 30 or any(row['expression_hash'] not in checked for row in planned):
                raise RepairRecoveryPending('Discovery source queue or in-flight evidence requires recovery')
            return [{**row, 'parent_alpha_id': parent['alpha_id'],
                     'parent_expression_hash': parent['expression_hash']} for row in rows]
        except RateLimitRecoveryRequired as exc:
            raise RepairRateLimited(exc.retry_at, exc.source_run_dir) from exc
        except requests.exceptions.RequestException as exc:
            if getattr(getattr(exc, 'response', None), 'status_code', 0) == 429:
                from wqb.rate_limit_state import record_rate_limit
                state = record_rate_limit(source, 'discovery_recovery', exc, {}, utc_now())
                raise RepairRateLimited(str(state['retry_at']), str(source)) from exc
            raise RepairRecoveryPending('Discovery network recovery pending; durable submission evidence preserved') from exc
