import { expect, test } from '@playwright/test';
import { createServer, type Server } from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const repo = path.resolve(__dirname, '../..');
const port = 18181;
let server: Server;
let wsCookie = '';
let sentMessage = '';
const upgradedSockets = new Set<any>();

const json = (response: any, body: unknown) => {
  response.writeHead(200, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(body));
};

async function staticFile(urlPath: string) {
  const relative = urlPath === '/' || !path.extname(urlPath) ? 'index.html' : urlPath.replace(/^\//, '');
  return readFile(path.join(repo, 'frontend-v2/dist', relative));
}

test.beforeAll(async () => {
  server = createServer(async (request, response) => {
    const url = new URL(request.url || '/', `http://127.0.0.1:${port}`);
    if (request.headers.upgrade?.toLowerCase() === 'websocket') return;
    if (url.pathname === '/teams/7.json') return json(response, { id: 7, name: '规划智库', enabled: true, question_room_id: 70, config: {} });
    if (url.pathname === '/rooms/list.json') return json(response, { rooms: [{ gt_room: { id: 70, team_id: 7, name: '问策正殿', type: 'group', tags: [] }, state: 'IDLE', agents: [-1, 701] }] });
    if (url.pathname === '/agents/list.json') return json(response, { agents: [{ id: 701, team_id: 7, name: '首席谋士', status: 'idle' }] });
    if (url.pathname === '/teams/7/activities.json') return json(response, { activities: [] });
    if (url.pathname === '/teams/7/tasks.json') return json(response, { tasks: [] });
    if (url.pathname === '/runs/current.json') return json(response, {});
    if (url.pathname === '/rooms/70/messages/list.json') return json(response, { messages: sentMessage ? [{ id: 1, room_id: 70, sender_id: -1, sender_name: '我', content: sentMessage, created_at: new Date().toISOString() }] : [] });
    if (url.pathname === '/rooms/70/messages/send.json' && request.method === 'POST') {
      let body = ''; request.on('data', chunk => body += chunk); request.on('end', () => { sentMessage = JSON.parse(body).content; json(response, { status: 'ok' }); }); return;
    }
    try {
      const content = await staticFile(url.pathname);
      response.writeHead(200, { 'Content-Type': url.pathname.endsWith('.js') ? 'text/javascript' : url.pathname.endsWith('.css') ? 'text/css' : 'text/html' });
      response.end(content);
    } catch {
      response.writeHead(404); response.end();
    }
  });
  server.on('upgrade', (request, socket) => {
    upgradedSockets.add(socket);
    socket.on('close', () => upgradedSockets.delete(socket));
    wsCookie = String(request.headers.cookie || '');
    const key = request.headers['sec-websocket-key'];
    if (!key) return socket.destroy();
    import('node:crypto').then(({ createHash }) => {
      const accept = createHash('sha1').update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest('base64');
      socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    });
  });
  await new Promise<void>(resolve => server.listen(port, '127.0.0.1', resolve));
});

test.afterAll(async () => {
  for (const socket of upgradedSockets) socket.destroy();
  await new Promise<void>(resolve => server.close(() => resolve()));
});

test('V2 uses the server question room, sends a consultation, and opens WS with Cookie', async ({ page, context }) => {
  await context.addCookies([{ name: 'dl_session', value: 'browser-session', domain: '127.0.0.1', path: '/' }]);
  await page.goto(`http://127.0.0.1:${port}/teams/7`);
  await expect(page.getByRole('heading', { name: '规划智库' })).toBeVisible();
  await page.getByRole('link', { name: '入殿问策' }).click();
  await expect(page).toHaveURL(/\/teams\/7\/rooms\/70$/);
  await page.getByLabel('向本室传讯').fill('请制定下一季度增长策略');
  await page.getByRole('button', { name: '飞鸽传书' }).click();
  await expect(page.getByLabel('讨论内容').getByText('请制定下一季度增长策略')).toBeVisible();
  await expect.poll(() => wsCookie).toContain('dl_session=browser-session');
});
