"""Deterministic four-sentence model briefs; detailed evidence remains separate."""

import json
import math
import re


MAX_LABEL_CHARS = 180
MAX_CHECKS = 6
MAX_HISTORY_SUMMARIES = 3
METRICS = ('sharpe', 'fitness', 'turnover')
MAX_HISTORY_CHECKS = 2
MAX_HISTORY_EDITS = 3


def _label(value: object) -> str:
    """Input: JSON value. Output: bounded single-clause str. Mark shortened descriptions."""
    text = re.sub(r'[.!?\u3002\uff01\uff1f\r\n]+', ' ', str(value)).strip()
    return text if len(text) <= MAX_LABEL_CHARS else text[:MAX_LABEL_CHARS] + ' [see full evidence]'


def _metrics(row: dict) -> str:
    """Input: measured row dict. Output: compact str. Preserve finite core metrics only."""
    metrics = row.get('metrics') or {}
    return ', '.join(name + '=' + (format(metrics[name], '.6g')
        if type(metrics.get(name)) in (int, float) and math.isfinite(metrics[name]) else 'unknown')
        for name in METRICS)


def _failures(row: dict) -> list:
    """Input: measured row dict. Output: distinct check-name list. Include adverse platform checks."""
    names = [_label(value) for value in row.get('failed') or []]
    checks = (row.get('metrics') or {}).get('checks', [])
    if isinstance(checks, list):
        names.extend(_label(check.get('name', 'unknown check')) for check in checks
                     if isinstance(check, dict) and check.get('result') in ('FAIL', 'WARNING'))
    return list(dict.fromkeys(names))


def build_repair_brief(evidence: dict) -> dict:
    """Input: full Repair evidence dict. Output: four single-sentence sections with explicit omissions."""
    parent = evidence['parent']
    knowledge = evidence.get('knowledge', {})
    hypotheses = [row.get('hypothesis') for row in knowledge.get('templates', []) if row.get('hypothesis')]
    # Compatible templates are not proof that this particular Alpha implements their hypothesis.
    hypothesis = ('compatible-template hypothesis (verify applicability): ' + _label(hypotheses[0])
                  if hypotheses else 'economic hypothesis unknown; read snapshot before inference')
    checks = (parent.get('metrics') or {}).get('checks', [])
    failures = [_label(value) for value in parent.get('failed') or []]
    thresholds = []
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict) or check.get('result') not in ('FAIL', 'WARNING'):
                continue
            name = _label(check.get('name', 'unknown check'))
            failures.append(name)
            # Keep numeric platform limits exact; never substitute an assumed benchmark.
            limit = check.get('limit', check.get('threshold'))
            if type(limit) in (int, float) and math.isfinite(limit):
                thresholds.append(name + '=' + json.dumps(limit))
    failures = list(dict.fromkeys(failures))
    failure_text = ', '.join(failures[:MAX_CHECKS]) or 'unknown or none recorded (not proof of pass)'
    if len(failures) > MAX_CHECKS:
        failure_text += '; additional failures in full evidence=' + str(len(failures) - MAX_CHECKS)
    threshold_text = ', '.join(thresholds[:MAX_CHECKS]) or 'unknown; consult full checks'
    history = evidence.get('history', [])
    summaries = []
    for row in history[-MAX_HISTORY_SUMMARIES:]:
        before, after = parent.get('settings') or {}, row.get('settings') or {}
        edits = []
        for key in sorted(set(before) | set(after)):
            if before.get(key) == after.get(key):
                continue
            value = after.get(key, 'missing')
            rendered = json.dumps(value) if type(value) in (int, float, bool) else _label(value)
            edits.append(_label(key) + '=' + rendered)
        if row.get('expression') != parent.get('expression'):
            edits.append('expression changed (see evidence)')
        edit_text = '; '.join(edits[:MAX_HISTORY_EDITS]) or 'edit unavailable/unchanged'
        if len(edits) > MAX_HISTORY_EDITS:
            edit_text += '; additional edits in full evidence=' + str(len(edits) - MAX_HISTORY_EDITS)
        adverse = _failures(row)
        adverse_text = ', '.join(adverse[:MAX_HISTORY_CHECKS]) or 'unknown or none recorded'
        if len(adverse) > MAX_HISTORY_CHECKS:
            adverse_text += '; additional adverse checks in full evidence=' + str(len(adverse) - MAX_HISTORY_CHECKS)
        summaries.append(_label(row.get('alpha_id', 'unknown')) + ' ' + edit_text + '; ' +
                         _metrics(row) + '; failed=' + adverse_text + '; hard_pass=' +
                         _label(row.get('hard_pass', 'unknown')))
    history_text = ('; '.join(summaries) + '; compare full edits and scope before retaining or repeating'
                    if summaries else 'no prior optimization recorded')
    if len(history) > MAX_HISTORY_SUMMARIES:
        history_text += '; earlier trials in full evidence=' + str(len(history) - MAX_HISTORY_SUMMARIES)
    return {
        'strategy': 'Alpha ' + _label(parent['parent_alpha_id']) + '; ' + hypothesis +
                    '; exact expression/settings in supporting evidence.',
        'problem': _metrics(parent) + '; failed checks: ' + failure_text + '; platform thresholds: ' + threshold_text + '.',
        'history': history_text + '.',
        'task': 'Select one measured target among sharpe/fitness/turnover and one allowed edit or stop; '
                'avoid other core metric regressions or new failed checks; remaining simulations=' +
                str(evidence['allowance']) + '; read supporting evidence for exact identity, edits and adverse results.',
    }
