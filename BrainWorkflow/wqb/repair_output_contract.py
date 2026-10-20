"""Conservative legacy command normalization, not a new research decision."""


NORMALIZATION_POLICY = 'repair-command-format-v1'
ALLOWANCE_WORDS = ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight')
LEGACY_STOP_FORMS = {'None; stop.', 'None; do not spend more simulations.'}


def normalize_legacy_decision(decision: dict, parent: dict, history: list = (), allowance: int = 0) -> dict:
    """Input: completed decision and exact parent dicts. Output: canonical copy. Reject ambiguous commands."""
    canonical = dict(decision)
    edit = decision.get('edit')
    stop_forms = set(LEGACY_STOP_FORMS)
    if type(allowance) is int and 0 <= allowance < len(ALLOWANCE_WORDS):
        for row in history:
            decay = (row.get('settings') or {}).get('decay')
            alpha_id = row.get('alpha_id')
            if type(decay) is not int or not isinstance(alpha_id, str):
                continue
            stop_forms.add(f'None; do not repeat decay={decay} or spend the '
                f'{ALLOWANCE_WORDS[allowance]} remaining simulations on this repair.')
            stop_forms.add(f'None; do not repeat decay={decay}. Next test: reconcile only the captured '
                f'{alpha_id} eligibility metadata and check statuses; unresolved disagreement preserves stop.')
    if decision.get('action') == 'stop' and isinstance(edit, str) and edit in stop_forms:
        canonical.update(edit='none', value=0)
        return canonical
    if decision.get('action') != 'neutralization':
        raise ValueError('Legacy Repair command is not unambiguously recoverable')
    settings = parent.get('settings') or {}
    required = ('neutralization', 'decay', 'region', 'delay', 'universe', 'instrumentType',
                'truncation', 'language', 'nanHandling', 'pasteurization', 'unitHandling', 'visualization')
    if any(key not in settings for key in required) or type(settings['visualization']) is not bool:
        raise ValueError('Legacy retained settings cannot be verified')
    value = decision.get('value')
    if value not in ('SUBINDUSTRY', 'INDUSTRY', 'SECTOR', 'MARKET'):
        raise ValueError('Legacy neutralization value invalid')
    expected = (f"Change only neutralization from {settings['neutralization']} to {value}. "
        f"Retain expression, decay={settings['decay']}, {settings['region']}/D{settings['delay']}/{settings['universe']}, "
        f"{settings['instrumentType']}, truncation={settings['truncation']}, {settings['language']}, "
        f"nanHandling={settings['nanHandling']}, pasteurization={settings['pasteurization']}, "
        f"unitHandling={settings['unitHandling']} and visualization={str(settings['visualization']).lower()}.")
    if edit != expected:
        raise ValueError('Legacy prose does not exactly retain the measured settings')
    canonical.update(action='test', edit='neutralization')
    return canonical
