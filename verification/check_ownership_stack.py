# 测试环境联调：真实 JWT、API、Redis 和 worker，不调用外部模型。
import sys
sys.path.insert(0, '/app')
import time
from uuid import uuid4
import httpx
from src.auth.security import AuthIdentity, issue_access_token
from src.database.connection import get_connection

with get_connection() as conn:
    assert conn.info.dbname == 'uav_project_test'
    users = [row[0] for row in conn.execute('SELECT id FROM users ORDER BY id LIMIT 2').fetchall()]
    assert len(users) == 2
    before = conn.execute('SELECT count(*) FROM flight_records').fetchone()[0]
client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=10)
for attempt in range(20):
    try:
        if client.get('/login').status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise RuntimeError('API startup timeout')
headers = [{'Authorization': 'Bearer ' + issue_access_token(AuthIdentity(uid, 'permission-check'))} for uid in users]
assert client.get('/flight/uavs').status_code == 401
for uid, auth in zip(users, headers):
    response = client.get('/flight/uavs', headers=auth)
    assert response.status_code == 200, response.text
    with get_connection() as conn:
        expected = {r[0] for r in conn.execute('SELECT id FROM uavs WHERE user_id=%s', (uid,))}
    assert {r['id'] for r in response.json()} == expected
    records = client.get('/flight/flights', headers=auth)
    assert records.status_code == 200, records.text
    with get_connection() as conn:
        for record in records.json():
            assert conn.execute('SELECT user_id FROM flight_records WHERE id=%s',(record['id'],)).fetchone()[0] == uid
    if expected:
        uav_id = next(iter(expected))
        foreign = client.get(f'/flight/uavs/{uav_id}/flights', headers=headers[1 if uid == users[0] else 0])
        assert foreign.status_code == 404, foreign.text
# 故意缺列，仅验证真实队列和身份传递，不调用 LLM。
submitted = client.post('/ai_flight/flights/report', headers=headers[0],
    data={'idempotency_key':str(uuid4())}, files={'file':('permission-invalid.csv',b'wrong_column\n1\n','text/csv')})
assert submitted.status_code == 202, submitted.text
task_id = submitted.json()['task_id']
assert client.get(f'/ai_flight/report/jobs/{task_id}', headers=headers[1]).status_code == 404
for attempt in range(20):
    result = client.get(f'/ai_flight/report/jobs/{task_id}', headers=headers[0])
    assert result.status_code == 200, result.text
    if result.json()['status'] in ('FAILED','FAILURE'):
        assert result.json()['error'] == 'INVALID_CSV', result.text
        break
    time.sleep(1)
else:
    raise RuntimeError('Worker task timeout')
with get_connection() as conn:
    assert conn.execute('SELECT user_id FROM celery_task_states WHERE task_id=%s',(task_id,)).fetchone()[0] == users[0]
    assert conn.execute('SELECT count(*) FROM flight_records').fetchone()[0] == before
print('PASS: JWT required; user-scoped UAV/flight reads; foreign UAV/task denied; worker restored owner; invalid CSV rejected without LLM or flight writes')
