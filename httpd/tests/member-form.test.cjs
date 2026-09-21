const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');

const html = readFileSync(require('node:path').join(__dirname, '../htdocs/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(postResponse) {
  const elements = {
    name: {value: '登録テスト 太郎'}, department: {value: '開発部'},
    email: {value: 'form-test@example.invalid'}, message: {}, rows: {}
  };
  const calls = [];
  const logs = [];
  const context = vm.createContext({
    // Browser built-in name is a string, even when an input has id="name".
    name: '', department: elements.department, email: elements.email,
    document: {getElementById: id => elements[id]}, performance,
    console: {info: (...args) => logs.push(args), warn: (...args) => logs.push(args)},
    fetch: async (path, options = {}) => {
      calls.push({path, options});
      if (options.method === 'POST') {
        if (postResponse instanceof Error) throw postResponse;
        return postResponse;
      }
      return response(200, []);
    }
  });
  vm.runInContext(script, context);
  return {context, elements, calls, logs};
}

function response(status, body) {
  return {ok: status < 400, status, headers: {get: () => 'test-request-id'}, json: async () => body};
}

test('registration sends input values despite window.name and refreshes the list', async () => {
  const {context, elements, calls, logs} = setup(response(201, {id: 123}));
  await context.createMember();
  const post = calls.find(c => c.options.method === 'POST');
  assert.deepEqual(JSON.parse(post.options.body), {
    name: elements.name.value, department: elements.department.value, email: elements.email.value
  });
  assert.equal(post.options.headers['Content-Type'], 'application/json');
  assert.equal(calls.at(-1).options.method, undefined);
  assert.equal(elements.message.className, 'ok');
  assert.ok(!JSON.stringify(logs).includes(elements.email.value));
  assert.ok(!JSON.stringify(logs).includes(elements.name.value));
});

test('validation failure is visible with request ID and error styling', async () => {
  const {context, elements} = setup(response(400, {error: 'name is required'}));
  await context.createMember();
  assert.match(elements.message.textContent, /name is required/);
  assert.match(elements.message.textContent, /test-request-id/);
  assert.equal(elements.message.className, 'ng');
});

test('network failure is shown instead of becoming an unhandled rejection', async () => {
  const {context, elements} = setup(new Error('network unavailable'));
  await context.createMember();
  assert.match(elements.message.textContent, /network unavailable/);
  assert.equal(elements.message.className, 'ng');
});
