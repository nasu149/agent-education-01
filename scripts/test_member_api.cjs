// Run against the deployed training app: node --test scripts/test_member_api.cjs
// Creates unique test records and removes only those records in finally.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const base = process.env.MEMBER_APP_URL || 'http://localhost:8088';

async function request(method, path = '', body) {
  const response = await fetch(base + '/api/members' + path, {
    method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  assert.match(response.headers.get('x-request-id') || '', /^[0-9a-f-]{36}$/);
  return {status: response.status, body: await response.json()};
}

test('deployed API: Japanese CRUD, validation, JSON errors and invalid IDs', async () => {
  const original = {name: 'API確認 太郎', department: '検証部署', email: `test-${randomUUID()}@example.invalid`};
  let id;
  try {
    const created = await request('POST', '', original);
    assert.equal(created.status, 201);
    id = created.body.id;
    assert.ok(Number.isInteger(id));
    const listed = await request('GET');
    assert.equal(listed.status, 200);
    assert.deepEqual(listed.body.find(member => member.id === id), {id, ...original});
    const updated = {...original, name: 'API確認 花子'};
    assert.equal((await request('PUT', '/' + id, updated)).status, 200);
    const filtered = await request('GET', '?name=' + encodeURIComponent(updated.name));
    assert.deepEqual(filtered.body.find(member => member.id === id), {id, ...updated});

    for (const method of ['POST', 'PUT']) {
      const path = method === 'PUT' ? '/' + id : '';
      for (const field of ['name', 'department', 'email']) {
        for (const value of [undefined, null, '', '   ', 123, {}]) {
          const result = await request(method, path, {...original, [field]: value});
          assert.equal(result.status, 400, `${method} ${field}=${JSON.stringify(value)}`);
          assert.match(result.body.error, new RegExp('^' + field + ' (is required|must be a string)$'));
        }
      }
      for (const invalid of [null, [], 'not an object']) {
        assert.equal((await request(method, path, invalid)).status, 400);
      }
    }
    const malformed = await fetch(base + '/api/members', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{invalid'
    });
    assert.equal(malformed.status, 400);
    assert.equal((await malformed.json()).error, 'valid JSON object is required');
    for (const path of ['', '/abc', '/0', '/-1']) {
      assert.equal((await request('PUT', path, original)).status, 400);
      assert.equal((await request('DELETE', path)).status, 400);
    }
    // Failed updates must not change the existing record.
    assert.deepEqual((await request('GET')).body.find(member => member.id === id), {id, ...updated});
    assert.equal((await request('DELETE', '/' + id)).status, 200);
    assert.equal((await request('DELETE', '/' + id)).status, 404);
    assert.equal((await request('PUT', '/' + id, original)).status, 404);
    assert.ok(!(await request('GET')).body.some(member => member.id === id));
    id = undefined;
  } finally {
    if (id !== undefined) {
      const cleanup = await request('DELETE', '/' + id);
      assert.ok([200, 404].includes(cleanup.status), 'test record cleanup failed');
    }
  }
});
