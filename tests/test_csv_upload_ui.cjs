// 用可控的页面、定时器和请求替身验证上传闭环，不调用模型或写数据库。
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");

const template = readFileSync(path.join(__dirname, "../app/templates/chat.html"), "utf8");
const source = template.match(/<script>([\s\S]*?)<\/script>/)[1];

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.hidden = true;
    this.disabled = false;
    this.files = [];
    this.value = "";
    this.ownText = "";
  }
  set textContent(text) { this.ownText = String(text); this.children = []; }
  get textContent() { return this.ownText + this.children.map(child => child.textContent).join(""); }
  set innerHTML(value) { throw new Error("页面不应执行文件或模型返回的 HTML"); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren() { this.children = []; this.ownText = ""; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  async fire(name) { await this.listeners[name]({preventDefault() {}}); }
}

function page(responses, savedTask = null) {
  const ids = [...template.matchAll(/id="([^"]+)"/g)].map(match => match[1]);
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const button = new Element();
  elements["csv-upload-form"].querySelector = () => button;
  elements["csv-upload-panel"].dataset.storageKey = "csv-report:1:new";
  const requests = [];
  const timers = new Map();
  const stored = new Map(savedTask ? [["csv-report:1:new", JSON.stringify(savedTask)]] : []);
  let timerId = 0;
  let keyId = 0;
  const context = {
    document: {
      getElementById: id => elements[id],
      createElement: () => new Element(),
    },
    window: {addEventListener() {}},
    sessionStorage: {
      setItem: (key, value) => stored.set(key, value),
      getItem: key => stored.get(key) || null,
      removeItem: key => stored.delete(key),
    },
    crypto: {randomUUID: () => `key-${++keyId}`},
    FormData: class {
      constructor() { this.fields = new Map(); }
      set(key, value) { this.fields.set(key, value); }
    },
    AbortController,
    Intl,
    encodeURIComponent,
    setTimeout: (callback, delay) => { timers.set(++timerId, {callback, delay}); return timerId; },
    clearTimeout: id => timers.delete(id),
    fetch: async (url, options) => {
      requests.push({url, options});
      const next = responses.shift();
      if (!next) throw new Error("没有预设请求结果");
      if (next instanceof Error) throw next;
      const status = next.http || 200;
      return {status, ok: status >= 200 && status < 300, json: async () => next.body};
    },
  };
  vm.runInNewContext(source, context);
  const flush = () => new Promise(resolve => setImmediate(resolve));
  return {
    elements, button, requests, timers, stored, flush,
    async select() {
      elements["csv-file"].files = [{name: "flights.csv"}];
      await elements["csv-file"].fire("change");
    },
    async submit() {
      await elements["csv-upload-form"].fire("submit");
      await flush();
    },
    async tick() {
      const [id, timer] = [...timers.entries()][0];
      timers.delete(id);
      await timer.callback();
      await flush();
    },
  };
}

function success() {
  return {body: {status: "SUCCESS", result: {
    filename: "flights.csv", flight_count: 2,
    flights: [1, 2].map(id => ({
      id, uav_code: `UAV-0${id}`, csv_flight_id: `CSV-0${id}`,
      summary: {row_count: 6, average_height: id * 20},
      ai_report: {
        conclusion: `报告${id}<img src=x onerror=alert(1)>`,
        observations: ["独立统计"], attention_items: ["关注电量"], limitations: [],
      },
    })),
  }}};
}

test("上传后轮询至成功，按飞行记录分别展示报告并停止定时器", async () => {
  const ui = page([
    {http: 202, body: {task_id: "task-1", status: "PENDING"}},
    {body: {status: "RUNNING"}}, success(),
  ]);
  await ui.select();
  await ui.submit();
  assert.equal(ui.button.disabled, true);
  assert.match(ui.elements["csv-upload-status"].textContent, /正在分析/);
  await ui.tick();
  assert.equal(ui.button.disabled, false);
  assert.match(ui.elements["csv-upload-status"].textContent, /分析完成/);
  assert.equal(ui.elements["csv-report-result"].children.length, 3);
  assert.match(ui.elements["csv-report-result"].textContent, /UAV-01/);
  assert.match(ui.elements["csv-report-result"].textContent, /UAV-02/);
  assert.match(ui.elements["csv-report-result"].textContent, /采样行数6/);
  assert.match(ui.elements["csv-report-result"].textContent, /<img src=x/);
  assert.equal(ui.timers.size, 0);
  assert.deepEqual(ui.requests.map(item => item.url), [
    "/ai_flight/flights/report", "/ai_flight/report/jobs/task-1", "/ai_flight/report/jobs/task-1",
  ]);
  assert.equal(ui.requests[1].options.credentials, "same-origin");
});

for (const http of [409, 503]) {
  test(`提交返回 ${http} 时查询原任务，不创建第二个任务`, async () => {
    const body = http === 409 ? {task_id: "original"} : {detail: {task_id: "original"}};
    const ui = page([{http, body}, success()]);
    await ui.select();
    await ui.submit();
    assert.equal(ui.requests.filter(item => item.options.method === "POST").length, 1);
    assert.equal(ui.requests[1].url, "/ai_flight/report/jobs/original");
    assert.equal(ui.timers.size, 0);
  });
}

test("CSV 校验失败时显示原因并停止轮询", async () => {
  const ui = page([
    {http: 202, body: {task_id: "task-1"}},
    {body: {status: "FAILED", error: "INVALID_CSV", detail: "缺少 uav_code"}},
  ]);
  await ui.select();
  await ui.submit();
  assert.match(ui.elements["csv-upload-detail"].textContent, /缺少 uav_code/);
  assert.equal(ui.elements["csv-report-result"].hidden, true);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.timers.size, 0);
});

test("缓存更新失败明确告知已保存记录，避免重复上传", async () => {
  const ui = page([
    {http: 202, body: {task_id: "task-1"}},
    {body: {status: "FAILURE", error: "CACHE_UPDATE_FAILED", detail: {record_ids: [17, 18]}}},
  ]);
  await ui.select();
  await ui.submit();
  assert.match(ui.elements["csv-upload-detail"].textContent, /已保存.*17、18.*请勿重复上传/);
});

test("查询断网自动重试，暂停后可继续查询而不重新上传", async () => {
  const ui = page([
    {http: 202, body: {task_id: "task-1"}},
    new Error("offline"), new Error("offline"), new Error("offline"), success(),
  ]);
  await ui.select();
  await ui.submit();
  await ui.tick();
  await ui.tick();
  assert.equal(ui.elements["csv-retry-query"].hidden, false);
  assert.equal(ui.timers.size, 0);
  await ui.elements["csv-retry-query"].fire("click");
  await ui.flush();
  assert.match(ui.elements["csv-upload-status"].textContent, /分析完成/);
  assert.equal(ui.requests.filter(item => item.options.method === "POST").length, 1);
});

test("登录失效停止轮询并展示重新登录入口", async () => {
  const ui = page([
    {http: 202, body: {task_id: "task-1"}}, {http: 401, body: {}},
  ]);
  await ui.select();
  await ui.submit();
  assert.equal(ui.elements["csv-login-link"].hidden, false);
  assert.match(ui.elements["csv-upload-status"].textContent, /登录已过期/);
  assert.equal(ui.timers.size, 0);
});

test("上传断网重试保留同一个幂等键", async () => {
  const ui = page([
    new Error("offline"), {http: 202, body: {task_id: "task-1"}}, success(),
  ]);
  await ui.select();
  await ui.submit();
  await ui.submit();
  const posts = ui.requests.filter(item => item.options.method === "POST");
  assert.equal(posts[0].options.body.fields.get("idempotency_key"),
               posts[1].options.body.fields.get("idempotency_key"));
});

test("刷新页面后恢复查询该页面最近的任务", async () => {
  const ui = page([success()], {task_id: "saved-task", filename: "flights.csv"});
  await ui.flush();
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.requests[0].url, "/ai_flight/report/jobs/saved-task");
  assert.match(ui.elements["csv-upload-status"].textContent, /分析完成/);
});

