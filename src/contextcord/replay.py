"""Read-only, deterministic audit timeline. Never executes historical commands."""
from .store import StateStore


def replay(repo, *, task_id=None, after=0, limit=1000):
    if not isinstance(after, int) or after < 0 or not isinstance(limit, int) or not 1 <= limit <= 10000:
        raise ValueError('invalid_replay_pagination')
    with StateStore(repo) as store:
        ok, bad = store.verify_event_chain()
        if not ok:
            return {'status': 'FAIL', 'bad_event': bad, 'events': []}
        import json
        sql = 'SELECT * FROM events WHERE seq > ?'
        params = [after]
        if task_id:
            sql += ' AND task_id = ?'; params.append(task_id)
        sql += ' ORDER BY seq LIMIT ?'; params.append(limit)
        events = []
        for row in store.conn.execute(sql, params):
            event = dict(row); event['payload'] = json.loads(event.pop('payload_json'))
            events.append(event)
        return {'status': 'PASS', 'store_id': store.store_id, 'head': store.event_chain_head(),
                'events': events, 'next_after': events[-1]['seq'] if events else after,
                'semantics': 'verified audit timeline; no command execution or state restoration'}
