import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { mkdir, readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import assert from 'node:assert/strict';

const BROWSER_MODULE = process.argv[2];
const TASK_MODE = process.argv.includes('--tasks');
const OUTPUT = resolve('../output/desktop-validation/projection');
const ROOT = resolve('dist');
const { chromium } = createRequire(import.meta.url)(BROWSER_MODULE);
const snapshot = JSON.parse(execFileSync('python', ['-c',
  'import json; from tests.test_console_api import projection_fixture; print(json.dumps(projection_fixture()))'],
{ cwd: resolve('..'), encoding: 'utf8' }));
snapshot.allowed_actions = { start: false, stop: false };
snapshot.blocker = 'Offline projection fixture; no research authority';
if (TASK_MODE) {
  Object.assign(snapshot, { task_mode: 1, start_mode: 'new', selected_task_id: 'ALL_LARGE_D1_20261127T100000_a1b2c3d4',
    options: [{ option_id: 'offline-option', title: 'Offline task fixture', startable: true, scope: { region: 'ALL', universe: 'LARGE', delay: 1 } }],
    allowed_actions: { start: true, stop: true }, tasks: [
      { task_id: 'ALL_LARGE_D1_20261127T100000_a1b2c3d4', status: 'failed', reason: 'Unverified parameter; experiment ended', selection: {}, created_at: '', ended_at: '', report_path: '/fixture/report.md' },
      { task_id: 'USA_TOP3000_D1_20261127T100100_b1c2d3e4', status: 'running', reason: '', selection: {}, created_at: '', ended_at: '', report_path: '' },
    ] });
}
let sequence = snapshot.sequence;

// Input: local HTTP request/response. Output: fixture-only API/static response; never invokes a workflow command.
const server = createServer(async (request, response) => {
  if (request.method !== 'GET') { response.writeHead(405).end(); return; }
  const url = new URL(request.url, 'http://127.0.0.1');
  const view = { ...snapshot, sequence: ++sequence, ...(TASK_MODE ? { selected_task_id: url.searchParams.get('task_id') || snapshot.selected_task_id } : {}) };
  if (url.pathname === '/api/application/snapshot') {
    response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(view)); return;
  }
  if (url.pathname === '/api/application/report') {
    response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ body: '# Offline research report\n\nPoint 1: unknown parameter; no Alpha submitted.' })); return;
  }
  if (url.pathname === '/api/application/events') {
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    response.write(`event: snapshot\ndata: ${JSON.stringify(view)}\n\n`); return;
  }
  const path = resolve(ROOT, '.' + (request.url === '/' ? '/index.html' : request.url));
  if (!path.startsWith(ROOT + '/') && !path.startsWith(ROOT + '\\')) { response.writeHead(403).end(); return; }
  try {
    const body = await readFile(path);
    response.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(path)] || 'application/octet-stream' }).end(body);
  } catch { response.writeHead(404).end(); }
});

await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => route.request().url().startsWith('http://127.0.0.1:') ? route.continue() : route.abort());
  await mkdir(OUTPUT, { recursive: true });
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    await page.setViewportSize(viewport);
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    if (TASK_MODE) {
      const task = page.getByRole('button', { name: /USA_TOP3000_D1_20261127T100100_b1c2d3e4/ });
      await task.click();
      await page.waitForFunction(() => document.querySelector('.task-select[aria-pressed="true"]')?.textContent.includes('USA_TOP3000'));
      await page.getByRole('button', { name: /查看 ALL_LARGE_D1.*研究报告/ }).click();
      await page.getByText('# Offline research report', { exact: false }).waitFor();
      await page.getByRole('button', { name: '关闭报告' }).click();
      await page.screenshot({ path: resolve(OUTPUT, `${name}-tasks.png`) });
    }
    await page.getByRole('button', { name: '查看legacy-run' }).click();
    await page.getByRole('heading', { name: '基线组' }).waitFor();
    assert.equal(await page.getByText('rank(ts_mean(fixture_x, 22))', { exact: true }).count(), 1);
    assert.equal(await page.getByRole('button', { name: /Start/ }).isDisabled(), !TASK_MODE);
    const detail = page.getByTestId('node-detail-scroll');
    await page.screenshot({ path: resolve(OUTPUT, `${name}-pair.png`) });
    await page.getByRole('heading', { name: '处理组' }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(OUTPUT, `${name}-treatment.png`) });
    await page.getByRole('tab', { name: /Seed/ }).click();
    await page.getByText('评分 0.75 · Sharpe 1.5', { exact: true }).waitFor();
    await page.getByRole('tab', { name: /Repair/ }).click();
    await page.getByTestId('repair-scroll').getByText('rank(ts_delta(fixture_x, 5))', { exact: true }).waitFor();
    await page.screenshot({ path: resolve(OUTPUT, `${name}-repair.png`) });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ screenshots: OUTPUT, viewports: 2, pageErrors: errors }));
} finally {
  await browser?.close();
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
}
