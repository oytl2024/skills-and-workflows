// Offline browser latency: mocked actions, actual built React/SSE rendering.
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import assert from 'node:assert/strict';

const SAMPLES = 12;
const OUTPUT = resolve('../output/desktop-validation/application-latency.json');
const ROOT = resolve('dist');
const { chromium } = createRequire(import.meta.url)(process.argv[2]);
const snapshot = JSON.parse(execFileSync('python', ['-c',
  'import json; from tests.test_console_api import projection_fixture; print(json.dumps(projection_fixture()))'],
{ cwd: resolve('..'), encoding: 'utf8' }));
snapshot.allowed_actions = { start: true, stop: true };
snapshot.blocker = '';
snapshot.request_revision = 'fixture-0';
snapshot.lanes.push({ ...structuredClone(snapshot.lanes[0]), lane_id: 'fixture-lane-two', name: 'fixture-lane-two' });
let clients = new Set();
const samples = { cold_render: [], click_to_pending: [], mock_http_ack: [], sse_to_view: [], cached_lane_switch: [] };

// Input: fixture mutation. Output: complete monotonic SSE snapshot to active local clients.
function push() {
  snapshot.sequence += 1;
  snapshot.evidence_at = new Date().toISOString();
  for (const client of clients) client.write(`event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`);
}

const server = createServer(async (request, response) => {
  if (request.url === '/api/application/snapshot') {
    response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(snapshot)); return;
  }
  if (request.url === '/api/application/events') {
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    clients.add(response);
    response.write(`event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`);
    response.on('close', () => clients.delete(response)); return;
  }
  if (request.method === 'POST' && request.url === '/api/application/commands') {
    let body = '';
    for await (const chunk of request) body += chunk;
    const command = JSON.parse(body);
    setTimeout(() => {
      response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({
        command_id: command.command_id, status: 'accepted', job_id: 'fixture-only', message: '' }));
      snapshot.request_revision = `fixture-${snapshot.sequence + 1}`;
      push();
    }, 30);
    return;
  }
  if (request.method !== 'GET') { response.writeHead(405).end(); return; }
  const path = resolve(ROOT, '.' + (request.url === '/' ? '/index.html' : request.url));
  if (!path.startsWith(ROOT + '/') && !path.startsWith(ROOT + '\\')) { response.writeHead(403).end(); return; }
  try {
    response.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(path)] || 'application/octet-stream' });
    response.end(await readFile(path));
  } catch { response.writeHead(404).end(); }
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const url = `http://127.0.0.1:${server.address().port}`;
  await page.route('**/*', route => route.request().url().startsWith(url) ? route.continue() : route.abort());
  for (let i = 0; i < 5; i++) {
    const start = performance.now();
    await page.goto(url);
    await page.getByRole('button', { name: '查看fixture-lane-two', exact: true }).waitFor();
    samples.cold_render.push(performance.now() - start);
  }
  await page.getByRole('button', { name: '下一个流程', exact: true }).click();
  for (let i = 0; i < SAMPLES; i++) {
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Start')?.disabled);
    const pending = await page.evaluate(() => new Promise(done => {
      const button = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Start');
      const start = performance.now();
      const observer = new MutationObserver(() => {
        if (button.disabled) { observer.disconnect(); done(performance.now() - start); }
      });
      observer.observe(button, { attributes: true });
      button.click();
    }));
    samples.click_to_pending.push(pending);
    const ackStart = performance.now();
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Start')?.disabled);
    samples.mock_http_ack.push(performance.now() - ackStart);
    const target = i % 2 === 0 ? '下一个流程' : '上一个流程';
    const navigation = performance.now();
    await page.getByRole('button', { name: target, exact: true }).click();
    await page.locator('.page-count').filter({ hasText: i % 2 === 0 ? '2 / 2' : '1 / 2' }).waitFor();
    samples.cached_lane_switch.push(performance.now() - navigation);
    const marker = `fixture evidence ${i}`;
    snapshot.blocker = marker;
    const update = performance.now();
    push();
    await page.getByRole('alert').filter({ hasText: marker }).waitFor();
    samples.sse_to_view.push(performance.now() - update);
  }
  const summary = Object.fromEntries(Object.entries(samples).map(([name, values]) => {
    const sorted = [...values].sort((a, b) => a - b);
    return [name, { samples: values.length, p50_ms: sorted[Math.ceil(values.length * .5) - 1], p95_ms: sorted[Math.ceil(values.length * .95) - 1] }];
  }));
  assert(samples.click_to_pending.every(Number.isFinite));
  const report = { scope: 'Offline built React/local fixture SSE; 2 lanes; no platform/model or durable backend actions. HTTP ack includes injected 30ms delay; cold_render excludes Python/backend/EXE startup.', summary, raw: samples };
  await mkdir(resolve('../output/desktop-validation'), { recursive: true });
  await writeFile(OUTPUT, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ report: OUTPUT, summary }));
} finally {
  await browser?.close();
  server.closeAllConnections();
  await new Promise(done => server.close(done));
}
