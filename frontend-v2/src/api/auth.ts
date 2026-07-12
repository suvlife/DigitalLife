import { reactive, readonly } from 'vue';

export const TOKEN_STORAGE_KEY = 'teamagent_token';

interface AuthState {
  required: boolean;
  reason: string;
  hasToken: boolean;
}

const state = reactive<AuthState>({
  required: false,
  reason: '',
  hasToken: Boolean(localStorage.getItem(TOKEN_STORAGE_KEY)?.trim()),
});

export function getToken(): string | null {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)?.trim();
  return token || null;
}

export function saveToken(token: string): void {
  const normalized = token.trim();
  if (normalized) localStorage.setItem(TOKEN_STORAGE_KEY, normalized);
  else localStorage.removeItem(TOKEN_STORAGE_KEY);
  state.hasToken = Boolean(normalized);
  state.required = false;
  state.reason = '';
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  state.hasToken = false;
}

export function requireAuthentication(reason = '请输入访问 Token 后重试'): void {
  state.required = true;
  state.reason = reason;
  state.hasToken = Boolean(getToken());
}

export function authenticationAccepted(): void {
  state.required = false;
  state.reason = '';
  state.hasToken = Boolean(getToken());
}

export const auth = { state: readonly(state), getToken, saveToken, clearToken, requireAuthentication, authenticationAccepted };
