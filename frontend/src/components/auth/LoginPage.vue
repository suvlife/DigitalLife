<script setup lang="ts">
import { ref, computed } from 'vue';
import { login, register, type UserInfo } from '../../api';

const emit = defineEmits<{
  (e: 'loggedIn', user: UserInfo): void;
}>();

const mode = ref<'login' | 'register'>('login');
const username = ref('');
const password = ref('');
const confirmPassword = ref('');
const displayName = ref('');
const loading = ref(false);
const errorMsg = ref('');

const isRegister = computed(() => mode.value === 'register');

async function handleSubmit() {
  errorMsg.value = '';

  if (!username.value.trim() || !password.value) {
    errorMsg.value = '用户名和密码不能为空';
    return;
  }

  if (isRegister.value) {
    if (password.value !== confirmPassword.value) {
      errorMsg.value = '两次输入的密码不一致';
      return;
    }
    if (password.value.length < 6) {
      errorMsg.value = '密码至少 6 位';
      return;
    }
  }

  loading.value = true;
  try {
    const result = isRegister.value
      ? await register(username.value.trim(), password.value, displayName.value.trim() || undefined)
      : await login(username.value.trim(), password.value);

    if (result.status === 'ok' && result.user) {
      emit('loggedIn', result.user);
    } else {
      errorMsg.value = '登录失败，请重试';
    }
  } catch (e: any) {
    errorMsg.value = e?.message || '网络错误，请重试';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <h1 class="login-title">数字人生</h1>
        <p class="login-subtitle">多智能体协作平台</p>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
        <div class="form-field">
          <label class="form-label">用户名</label>
          <input
            v-model="username"
            type="text"
            class="form-input"
            placeholder="请输入用户名"
            autocomplete="username"
            :disabled="loading"
          />
        </div>

        <div class="form-field">
          <label class="form-label">密码</label>
          <input
            v-model="password"
            type="password"
            class="form-input"
            placeholder="请输入密码"
            autocomplete="current-password"
            :disabled="loading"
          />
        </div>

        <template v-if="isRegister">
          <div class="form-field">
            <label class="form-label">确认密码</label>
            <input
              v-model="confirmPassword"
              type="password"
              class="form-input"
              placeholder="再次输入密码"
              autocomplete="new-password"
              :disabled="loading"
            />
          </div>

          <div class="form-field">
            <label class="form-label">显示名称（可选）</label>
            <input
              v-model="displayName"
              type="text"
              class="form-input"
              placeholder="昵称"
              :disabled="loading"
            />
          </div>
        </template>

        <div v-if="errorMsg" class="form-error">{{ errorMsg }}</div>

        <button type="submit" class="login-button" :disabled="loading">
          {{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}
        </button>

        <div class="login-switch">
          <span v-if="!isRegister">
            没有账号？
            <a href="#" @click.prevent="mode = 'register'">注册</a>
          </span>
          <span v-else>
            已有账号？
            <a href="#" @click.prevent="mode = 'login'">登录</a>
          </span>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--surface-page);
  padding: 20px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 40px 32px;
  box-shadow: var(--shadow-panel);
}

.login-brand {
  text-align: center;
  margin-bottom: 32px;
}

.login-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
}

.login-subtitle {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.form-input {
  padding: 10px 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--surface-input);
  color: var(--text-primary);
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.form-input:focus {
  border-color: var(--interactive-focus-border);
}

.form-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-error {
  color: var(--state-danger);
  font-size: 13px;
  padding: 4px 0;
}

.login-button {
  padding: 12px;
  border: none;
  border-radius: 8px;
  background: var(--interactive-selected);
  color: var(--text-on-accent);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
  margin-top: 8px;
}

.login-button:hover:not(:disabled) {
  opacity: 0.9;
}

.login-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-switch {
  text-align: center;
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 8px;
}

.login-switch a {
  color: var(--interactive-selected);
  text-decoration: none;
}

.login-switch a:hover {
  text-decoration: underline;
}
</style>
