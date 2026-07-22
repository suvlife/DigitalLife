import { connectionState, reconnectProgress, authEnabled, showTokenDialog } from '../appUiState';
import { createEventsSocket } from '../api';
import { getToken, clearToken } from '../authStore';
import { normalizeWsEventPayload, type FrontendRealtimeEvent } from './eventNormalizer';

type RealtimeListener = (event: FrontendRealtimeEvent) => void;

const reconnectDelayMs = 3000;
const connectTimeoutMs = 2000;
// 应用层心跳间隔：探测 NAT/代理空闲断连（比 Tornado 服务端 30s ping 更早发现死连接）。
const heartbeatIntervalMs = 25000;

const listeners = new Set<RealtimeListener>();

let ws: WebSocket | null = null;
let reconnectTimer: number | null = null;
let reconnectCountdownTimer: number | null = null;
let connectTimeoutTimer: number | null = null;
let heartbeatTimer: number | null = null;
let reconnectAttempt = 0;
let activeSocketToken = 0;
let started = false;

function clearReconnectCountdown(): void {
  reconnectProgress.value = 0;
  if (reconnectCountdownTimer !== null) {
    window.clearInterval(reconnectCountdownTimer);
    reconnectCountdownTimer = null;
  }
}

function clearConnectTimeout(): void {
  if (connectTimeoutTimer !== null) {
    window.clearTimeout(connectTimeoutTimer);
    connectTimeoutTimer = null;
  }
}

function startHeartbeat(socket: WebSocket): void {
  stopHeartbeat();
  heartbeatTimer = window.setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({ type: 'ping' }));
      } catch {
        // 发送失败说明连接已死，交由 close/超时逻辑处理
      }
    }
  }, heartbeatIntervalMs);
}

function stopHeartbeat(): void {
  if (heartbeatTimer !== null) {
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function startReconnectCountdown(delayMs: number): void {
  const reconnectAt = Date.now() + delayMs;

  const syncCountdown = (): void => {
    const remainingMs = reconnectAt - Date.now();
    const clampedRemaining = Math.min(Math.max(remainingMs, 0), delayMs);
    reconnectProgress.value = 1 - clampedRemaining / delayMs;
  };

  clearReconnectCountdown();
  syncCountdown();
  reconnectCountdownTimer = window.setInterval(syncCountdown, 50);
}

function emitRealtimeEvent(event: FrontendRealtimeEvent): void {
  for (const listener of listeners) {
    listener(event);
  }
}

function scheduleReconnect(): void {
  if (!started) {
    return;
  }
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
  }

  reconnectAttempt += 1;
  connectionState.value = 'waiting_reconnect';
  // 审计 L10：指数退避（上限 30s），与 frontend-v2 一致，避免后端宕机期间固定 3s 高频重连压力。
  const backoffMs = Math.min(30000, reconnectDelayMs * 2 ** (reconnectAttempt - 1));
  startReconnectCountdown(backoffMs);
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    clearReconnectCountdown();
    connectRealtimeSocket();
  }, backoffMs);
}

function connectRealtimeSocket(): void {
  if (!started) {
    return;
  }

  activeSocketToken += 1;
  const socketToken = activeSocketToken;
  const isReconnectAttempt = reconnectAttempt > 0;

  clearConnectTimeout();

  if (ws) {
    ws.close();
    ws = null;
  }

  connectionState.value = isReconnectAttempt ? 'reconnecting' : 'connecting';
  clearReconnectCountdown();

  const socket = createEventsSocket();
  ws = socket;

  connectTimeoutTimer = window.setTimeout(() => {
    // 首连（connecting）与重连（reconnecting）都需要超时保护：
    // 此前守卫只放行 reconnecting，导致首次连接卡住时永不触发重连。
    if (
      socketToken !== activeSocketToken ||
      (connectionState.value !== 'reconnecting' && connectionState.value !== 'connecting')
    ) {
      return;
    }

    clearConnectTimeout();
    socket.close();
    ws = null;
    connectionState.value = 'disconnected';
    scheduleReconnect();
  }, connectTimeoutMs);

  socket.addEventListener('open', () => {
    if (socketToken !== activeSocketToken) {
      return;
    }

    clearConnectTimeout();
    startHeartbeat(socket);

    // 鉴权启用时，发送认证消息
    if (authEnabled.value) {
      const token = getToken();
      if (token) {
        socket.send(JSON.stringify({ type: 'auth', token }));
        // 连接状态暂时保持 'connecting'，等待后端确认
      } else {
        // 无 token，关闭连接并触发输入
        socket.close();
        ws = null;
        showTokenDialog.value = true;
        return;
      }
    } else {
      // 鉴权未启用，直接标记为已连接
      connectionState.value = 'connected';
      reconnectAttempt = 0;
    }

    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    clearReconnectCountdown();
  });

  socket.addEventListener('message', (messageEvent) => {
    if (socketToken !== activeSocketToken) {
      return;
    }

    // 鉴权启用时，第一条消息到达表示认证成功。
    // 重连期间状态是 'reconnecting'，与首次 'connecting' 一样需要迁移，
    // 否则重连成功后永远卡在重连态、断线期间的刷新 watcher 不再触发。
    if (
      authEnabled.value &&
      (connectionState.value === 'connecting' || connectionState.value === 'reconnecting')
    ) {
      connectionState.value = 'connected';
      reconnectAttempt = 0;
    }

    try {
      const payload = JSON.parse(messageEvent.data);
      const normalized = normalizeWsEventPayload(payload);
      if (normalized) {
        emitRealtimeEvent(normalized);
      }
    } catch (error) {
      console.error(error);
    }
  });

  socket.addEventListener('close', (closeEvent?: CloseEvent) => {
    if (socketToken !== activeSocketToken) {
      return;
    }

    ws = null;
    stopHeartbeat();

    // 1008 (Policy Violation)：后端用于鉴权失败。此时无限重连无意义，
    // 清除无效 token 并弹出输入框，等待用户提供新凭据后手动重连。
    if (closeEvent?.code === 1008) {
      clearConnectTimeout();
      clearReconnectCountdown();
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      reconnectAttempt = 0;
      connectionState.value = 'disconnected';
      clearToken();
      showTokenDialog.value = true;
      return;
    }

    if (isReconnectAttempt && connectTimeoutTimer !== null && connectionState.value === 'reconnecting') {
      return;
    }

    clearConnectTimeout();
    connectionState.value = 'disconnected';
    scheduleReconnect();
  });

  socket.addEventListener('error', () => {
    if (socketToken !== activeSocketToken) {
      return;
    }

    if (isReconnectAttempt && connectTimeoutTimer !== null && connectionState.value === 'reconnecting') {
      return;
    }

    clearConnectTimeout();
    connectionState.value = 'disconnected';
  });
}

export function startRealtimeClient(): void {
  if (started) {
    return;
  }
  started = true;
  connectRealtimeSocket();
}

export function stopRealtimeClient(): void {
  started = false;
  activeSocketToken += 1;

  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  clearConnectTimeout();
  clearReconnectCountdown();
  stopHeartbeat();

  if (ws) {
    ws.close();
    ws = null;
  }

  reconnectAttempt = 0;
  connectionState.value = 'disconnected';
}

export function subscribeRealtimeEvents(listener: RealtimeListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function __resetWsClientForTests(): void {
  started = false;
  activeSocketToken += 1;

  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (reconnectCountdownTimer !== null) {
    window.clearInterval(reconnectCountdownTimer);
    reconnectCountdownTimer = null;
  }
  if (connectTimeoutTimer !== null) {
    window.clearTimeout(connectTimeoutTimer);
    connectTimeoutTimer = null;
  }
  if (heartbeatTimer !== null) {
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }

  listeners.clear();
  reconnectAttempt = 0;
  reconnectProgress.value = 0;
  connectionState.value = 'disconnected';
  showTokenDialog.value = false;
}
