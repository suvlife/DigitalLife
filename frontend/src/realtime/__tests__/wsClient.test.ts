import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { authEnabled, connectionState, showTokenDialog } from '../../appUiState';

const {
  createEventsSocketMock,
  getTokenMock,
  normalizeWsEventPayloadMock,
} = vi.hoisted(() => ({
  createEventsSocketMock: vi.fn(),
  getTokenMock: vi.fn(),
  normalizeWsEventPayloadMock: vi.fn(),
}));

vi.mock('../../api', () => ({
  createEventsSocket: createEventsSocketMock,
}));

vi.mock('../../authStore', () => ({
  getToken: getTokenMock,
  clearToken: vi.fn(),
}));

vi.mock('../eventNormalizer', () => ({
  normalizeWsEventPayload: normalizeWsEventPayloadMock,
}));

import {
  __resetWsClientForTests,
  startRealtimeClient,
  stopRealtimeClient,
  subscribeRealtimeEvents,
} from '../wsClient';

type ListenerMap = {
  open: Array<() => void>;
  close: Array<(event?: CloseEvent) => void>;
  error: Array<() => void>;
  message: Array<(event: MessageEvent<string>) => void>;
};

class FakeWebSocket {
  public readonly listeners: ListenerMap = {
    open: [],
    close: [],
    error: [],
    message: [],
  };

  public readonly sentMessages: string[] = [];

  public closeCount = 0;

  addEventListener<K extends keyof ListenerMap>(type: K, listener: ListenerMap[K][number]): void {
    this.listeners[type].push(listener as never);
  }

  send(payload: string): void {
    this.sentMessages.push(payload);
  }

  close(): void {
    this.closeCount += 1;
    this.emit('close');
  }

  /** 模拟带状态码的服务端关闭（如 1008 鉴权失败）。 */
  closeWithCode(code: number): void {
    this.closeCount += 1;
    const event = { code } as CloseEvent;
    this.listeners.close.forEach((listener) => listener(event));
  }

  emit(type: 'open' | 'close' | 'error'): void;
  emit(type: 'message', payload: string): void;
  emit(type: keyof ListenerMap, payload?: string): void {
    if (type === 'message') {
      const event = { data: payload ?? '' } as MessageEvent<string>;
      this.listeners.message.forEach((listener) => listener(event));
      return;
    }

    this.listeners[type].forEach((listener) => listener());
  }
}

describe('wsClient', () => {
  const sockets: FakeWebSocket[] = [];

  beforeEach(() => {
    vi.useFakeTimers();
    sockets.length = 0;
    createEventsSocketMock.mockImplementation(() => {
      const socket = new FakeWebSocket();
      sockets.push(socket);
      return socket;
    });
    getTokenMock.mockReset();
    normalizeWsEventPayloadMock.mockReset();
    authEnabled.value = false;
    __resetWsClientForTests();
  });

  afterEach(() => {
    stopRealtimeClient();
    __resetWsClientForTests();
    vi.useRealTimers();
  });

  it('connects immediately when auth is disabled', () => {
    startRealtimeClient();

    expect(connectionState.value).toBe('connecting');
    expect(sockets).toHaveLength(1);

    sockets[0]?.emit('open');

    expect(connectionState.value).toBe('connected');
  });

  it('authenticates with token and emits normalized realtime events', () => {
    authEnabled.value = true;
    getTokenMock.mockReturnValue('secret-token');
    const listener = vi.fn();
    const normalizedEvent = { type: 'schedule_state', scheduleState: 'running', notRunningReason: '' };
    normalizeWsEventPayloadMock.mockReturnValue(normalizedEvent);

    const unsubscribe = subscribeRealtimeEvents(listener);
    startRealtimeClient();
    sockets[0]?.emit('open');

    expect(connectionState.value).toBe('connecting');
    expect(sockets[0]?.sentMessages).toEqual([
      JSON.stringify({ type: 'auth', token: 'secret-token' }),
    ]);

    sockets[0]?.emit('message', JSON.stringify({ event: 'schedule_state' }));

    expect(connectionState.value).toBe('connected');
    expect(listener).toHaveBeenCalledWith(normalizedEvent);

    unsubscribe();
  });

  it('shows token dialog when auth is enabled but no token is available', () => {
    authEnabled.value = true;
    getTokenMock.mockReturnValue(null);

    startRealtimeClient();
    sockets[0]?.emit('open');

    expect(showTokenDialog.value).toBe(true);
    expect(sockets[0]?.closeCount).toBe(1);
  });

  it('schedules reconnects after socket close', () => {
    startRealtimeClient();
    sockets[0]?.emit('open');
    sockets[0]?.emit('close');

    expect(connectionState.value).toBe('waiting_reconnect');

    vi.advanceTimersByTime(3000);

    expect(sockets).toHaveLength(2);
    expect(connectionState.value).toBe('reconnecting');

    sockets[1]?.emit('open');

    expect(connectionState.value).toBe('connected');
  });

  it('marks the socket connected after reauthenticating on a reconnect', () => {
    authEnabled.value = true;
    getTokenMock.mockReturnValue('secret-token');

    startRealtimeClient();
    sockets[0]?.emit('open');
    sockets[0]?.emit('message', JSON.stringify({ event: 'schedule_state' }));
    expect(connectionState.value).toBe('connected');

    sockets[0]?.emit('close');
    expect(connectionState.value).toBe('waiting_reconnect');

    vi.advanceTimersByTime(3000);
    expect(sockets).toHaveLength(2);
    expect(connectionState.value).toBe('reconnecting');

    sockets[1]?.emit('open');
    expect(sockets[1]?.sentMessages).toEqual([
      JSON.stringify({ type: 'auth', token: 'secret-token' }),
    ]);
    // 重连认证期间保持 reconnecting，第一条消息到达才确认认证成功
    expect(connectionState.value).toBe('reconnecting');

    sockets[1]?.emit('message', JSON.stringify({ event: 'schedule_state' }));
    expect(connectionState.value).toBe('connected');
  });

  it('cancels pending reconnects when stopped', () => {
    startRealtimeClient();
    sockets[0]?.emit('open');
    sockets[0]?.emit('close');

    expect(connectionState.value).toBe('waiting_reconnect');

    stopRealtimeClient();
    vi.advanceTimersByTime(3000);

    expect(sockets).toHaveLength(1);
    expect(connectionState.value).toBe('disconnected');
  });

  it('reconnects when the initial connection times out', () => {
    // 首连（connecting 态）也应受超时保护：connectTimeoutMs 内未 open 即触发重连。
    startRealtimeClient();
    expect(connectionState.value).toBe('connecting');
    expect(sockets).toHaveLength(1);

    // 不触发 open，推进超过 connectTimeoutMs(2000)
    vi.advanceTimersByTime(2100);

    expect(connectionState.value).toBe('waiting_reconnect');

    // 推进超过首次退避（3000ms），分步推进以正确处理高频 countdown interval
    vi.advanceTimersByTime(30000);
    expect(sockets.length).toBeGreaterThanOrEqual(2);
    expect(connectionState.value).not.toBe('connecting');
  });

  it('stops reconnecting and prompts for token on 1008 auth failure', () => {
    authEnabled.value = true;
    getTokenMock.mockReturnValue('bad-token');

    startRealtimeClient();
    sockets[0]?.emit('open');
    expect(connectionState.value).toBe('connecting');

    // 后端鉴权失败以 1008 关闭：应停止重连、清 token 并弹出输入框，而非无限重试
    sockets[0]?.closeWithCode(1008);

    expect(connectionState.value).toBe('disconnected');
    expect(showTokenDialog.value).toBe(true);

    // 推进较长时间也不应自动重连
    vi.advanceTimersByTime(60000);
    expect(sockets).toHaveLength(1);
  });
});
