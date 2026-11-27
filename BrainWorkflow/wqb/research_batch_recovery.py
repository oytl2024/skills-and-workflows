"""Explicit maintenance recovery for historical batch-400 reservation misclassification.

Not a Start action, automatic terminal-task restart, or unknown-POST waiver.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from wqb.lockfile import json_lock_transition_guard
from wqb.research_tasks import _directory, _safe, read_task
from wqb.research_group import read_group
from wqb.runtime_control import _write


FAULT = 'simulation identity already reserved or outcome unknown; reconcile before retry'


def reopen_rejected_batch_task(root: Path, task_id: str, sources: list[Path], *, authorization: str) -> dict:
    """Input: runs root, failed task ID, source Paths, explicit approval str.

    Output: reopened same task dict. Only proven rejected multi-400 claims change;
    original plans, request identities, usage and all limits remain untouched.
    Does not spawn workers or make network requests. Ordinary Start cannot call it.
    """
    from wqb.cli import simulation_identity_hash
    from wqb.console_progress import process_is_alive
    root = _safe(root)
    if not isinstance(authorization, str) or not authorization.strip() or not sources:
        raise ValueError('explicit maintenance authorization and sources required')
    directory = _directory(root, task_id)
    shared = _safe(root/'research_groups')
    with json_lock_transition_guard(directory/'update',5,.02,'task update busy'), \
            json_lock_transition_guard(shared/'identity_guard',5,.05,'group identity busy'):
        task = read_task(root, task_id)
        if task['status'] != 'failed' or task.get('reason') != FAULT:
            raise ValueError('not the known failed batch fallback fault')
        runs = _safe(Path(task['runs_root']))
        group_path = _safe(Path(task['group_dir']))
        if group_path.parent.parent != runs:
            raise ValueError('group is not owned by task')
        group = read_group(group_path)
        if group['desired_state'] != 'paused':
            raise ValueError('quiescent group required')
        for lane in group['lanes']:
            run = runs/lane['run_id']
            worker = run/'runtime/group_worker.json'
            if worker.exists():
                row = json.loads(worker.read_text(encoding='utf-8'))
                if row.get('status') not in {'failed','exited'} or process_is_alive(row.get('pid')) is not False:
                    raise ValueError('worker is not confirmed stopped')
            control=run/'runtime_control.json'
            if control.exists() and json.loads(control.read_text(encoding='utf-8')).get('desired_state') != 'running':
                raise ValueError('durable lane Stop prevents recovery')
        path=shared/'simulation_reservations.json'
        claims=json.loads(path.read_text(encoding='utf-8'))
        evidence=[]
        verified=set()
        for source in sources:
            source=_safe(source)
            if source.parent != runs:
                raise ValueError('source is not owned by task')
            journal=_safe(source/'simulation_events.jsonl')
            errors=_safe(source/'run_errors.jsonl')
            events=[json.loads(s) for s in journal.read_text(encoding='utf-8').splitlines() if s.strip()]
            failures=[json.loads(s) for s in errors.read_text(encoding='utf-8').splitlines() if s.strip()]
            if not events or any(e.get('event') not in {'SUBMISSION_STARTED','SUBMISSION_REJECTED'} for e in events):
                raise ValueError('accepted or unresolved submission evidence')
            starts=[e for e in events if e.get('event')=='SUBMISSION_STARTED' and str(e.get('stage','')).endswith('_multi_submit')]
            attempts={e.get('attempt_id') for e in starts}
            if len(attempts)!=1 or len(starts)<2 or not next(iter(attempts)):
                raise ValueError('one definitive batch rejection required per source')
            if not any(f.get('status_code')==400 and f.get('payload_count')==len(starts)
                       and f.get('stage')==starts[0]['stage'] for f in failures):
                raise ValueError('batch HTTP 400 evidence missing')
            for event in starts:
                identity=simulation_identity_hash(event['expression'],event['settings'])
                receipt=_safe(Path(event['ai_plan_receipt']))
                lane=next((l['run_id'] for l in group['lanes']
                    if receipt.is_relative_to(runs/l['run_id']/'runtime/research_plans')),None)
                claim=claims.get(identity,{})
                rejected=any(e.get('event')=='SUBMISSION_REJECTED' and e.get('attempt_id')==event['attempt_id']
                    and e.get('expression_hash')==event['expression_hash'] for e in events)
                if (identity in verified or not lane or not rejected or claim.get('group_id')!=group_path.name
                        or claim.get('run_id')!=lane or claim.get('status_code')!=400 or claim.get('progress_url')
                        or claim.get('submission_status') not in {'sent','rejected_batch_400'}):
                    raise ValueError('claim ownership or definitive rejection not proven')
                verified.add(identity)
            evidence.append(dict(source=str(source),journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
                errors_sha256=hashlib.sha256(errors.read_bytes()).hexdigest()))
        for identity in verified:
            claims[identity]['submission_status']='rejected_batch_400'
        # Persist a local receipt before reopening; a crash never permits unknown POSTs.
        generation=task.get('recovery_generation',0)+1
        receipt=dict(authorization=authorization,evidence=evidence,identities=sorted(verified),
            prior_status=task['status'],prior_reason=task['reason'],prior_ended_at=task['ended_at'],
            recovery_generation=generation,at=datetime.now(timezone.utc).isoformat())
        _write(directory/('batch_recovery_'+str(generation)+'.json'),receipt)
        _write(path,claims)
        task.update(status='running',reason='',ended_at='',updated_at=receipt['at'],recovery_generation=generation)
        _write(directory/'task.json',task)
        return task


def release_batch_recovery_holds(root: Path, task_id: str, *, authorization: str) -> None:
    """Input: runs Path, explicitly recovered task ID, approval str. Output: None.

    Release only the stale pre-import Scout hold for this proven batch rejection;
    retain its original case and full snapshot in the recovery receipt. No proof
    renewal, budget change or general maintenance-case waiver is performed.
    """
    if not authorization.strip():
        raise ValueError('explicit recovery authorization required')
    task=read_task(root,task_id)
    generation=task.get('recovery_generation',0)
    if task['status']!='running' or not generation:
        raise ValueError('explicitly recovered running task required')
    directory=_directory(root,task_id)
    receipt_path=directory/('batch_recovery_'+str(generation)+'.json')
    receipt=json.loads(_safe(receipt_path).read_text(encoding='utf-8'))
    group=read_group(Path(task['group_dir']))
    if group['desired_state']!='paused':
        raise ValueError('pause group before releasing local hold')
    changes=[]
    for lane in group['lanes']:
        run=_safe(Path(task['runs_root'])/lane['run_id'])
        control_path=run/'runtime_control.json'
        control=json.loads(_safe(control_path).read_text(encoding='utf-8'))
        status_path=run/'runtime_status.json'
        status=json.loads(_safe(status_path).read_text(encoding='utf-8'))
        case=control.get('recovery_case') or status.get('recovery_case') or {}
        if not case:
            continue
        if (case.get('stage')!='scout_seed' or case.get('action')!='stage_failed'
                or case.get('status')!='awaiting_maintenance_confirmation'
                or not status.get('last_result',{}).get('pause_reason','').startswith('checked research results require completed tree:')):
            raise ValueError('unrelated maintenance hold must not be released')
        changes.append((control_path,control,status_path,status,case))
    receipt['released_preimport_holds']=[dict(run=str(p.parent),case=case) for p,_,_,_,case in changes]
    receipt['hold_release_authorization']=authorization
    _write(receipt_path,receipt)
    for control_path,control,status_path,status,_ in changes:
        _write(control_path,{key:value for key,value in control.items() if key!='recovery_case'})
        _write(status_path,{**status,'recovery_case':{}})
