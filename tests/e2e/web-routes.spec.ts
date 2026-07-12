import { expect, test } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';

const repo = path.resolve(__dirname, '../..');
const port = 18180;
let backend: ChildProcess | undefined;
let configDir = '';

async function waitForPort(portNumber: number) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const open = await new Promise<boolean>((resolve) => {
      const socket = net.connect(portNumber, '127.0.0.1');
      socket.once('connect', () => { socket.destroy(); resolve(true); });
      socket.once('error', () => resolve(false));
    });
    if (open) return;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`backend did not listen on ${portNumber}`);
}

test.beforeAll(async () => {
  configDir = await mkdtemp(path.join(os.tmpdir(), 'digitallife-e2e-'));
  await mkdir(path.join(configDir, 'role_templates'), { recursive: true });
  await mkdir(path.join(configDir, 'teams'), { recursive: true });
  await writeFile(path.join(configDir, 'setting.json'), JSON.stringify({
    workspace_root: path.join(configDir, 'workspace'),
    llm_services: [],
    default_llm_server: null,
    auth: { enabled: false },
  }));
  const repositoryPython = path.join(repo, '.venv', 'bin', 'python');
  const python = process.env.PYTHON || (existsSync(repositoryPython) ? repositoryPython : 'python3');
  backend = spawn(python, [
    'src/backend_main.py', '--config-dir', configDir, '--port', String(port),
  ], { cwd: repo, env: { ...process.env, PYTHONPATH: 'src' }, stdio: ['ignore', 'pipe', 'pipe'] });
  backend.stdout?.on('data', chunk => process.stdout.write(String(chunk)));
  backend.stderr?.on('data', chunk => process.stderr.write(String(chunk)));
  await waitForPort(port);
});

test.afterAll(async () => {
  backend?.kill('SIGTERM');
  await rm(configDir, { recursive: true, force: true });
});

test('server keeps V2 and classic shells isolated and redirects legacy V2 paths', async ({ request }) => {
  const root = await request.get('/');
  expect(root.status()).toBe(200);
  expect(await root.text()).toContain('<title>数字人生 · 江湖书院</title>');

  const classic = await request.get('/v1/');
  expect(classic.status()).toBe(200);
  const classicHtml = await classic.text();
  expect(classicHtml).not.toContain('<title>数字人生 · 江湖书院</title>');
  expect(classicHtml).toContain('<title>数字人生</title>');
  expect(classicHtml).toMatch(/\/(?:v1\/)?assets\//);

  const legacy = await request.get('/v2/archive?team=42', { maxRedirects: 0 });
  expect(legacy.status()).toBe(301);
  expect(legacy.headers().location).toBe('/archive?team=42');
});
