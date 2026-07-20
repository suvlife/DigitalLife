<script setup lang="ts">
import { world } from '../store/world';
import { useViewMode } from '../composables/useViewMode';
import StatusDot from '../components/StatusDot.vue';
import GlowButton from '../components/GlowButton.vue';
const { navigate } = useViewMode();
const connText = { open: '系统连接正常', connecting: '正在建立连接', closed: '连接已断开', error: '连接异常' };
</script>
<template>
  <header class="top-bar">
    <div class="bar-left">
      <div class="brand-logo">
        <svg width="28" height="28" viewBox="0 0 64 64" class="logo-svg">
          <defs><linearGradient id="lg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#00D9FF"/><stop offset="100%" stop-color="#7C3AED"/></linearGradient></defs>
          <path d="M 32 10 C 20 10, 10 18, 10 32 C 10 46, 20 54, 32 54 C 44 54, 54 46, 54 32 C 54 18, 44 10, 32 10 Z" fill="none" stroke="url(#lg)" stroke-width="4" stroke-linecap="round"/>
          <path d="M 14 24 C 22 30, 42 34, 50 40" fill="none" stroke="url(#lg)" stroke-width="4" stroke-linecap="round" opacity="0.85"/>
          <path d="M 50 24 C 42 30, 22 34, 14 40" fill="none" stroke="url(#lg)" stroke-width="4" stroke-linecap="round" opacity="0.85"/>
          <circle cx="32" cy="32" r="3" fill="url(#lg)" opacity="0.6"/>
        </svg>
        <div class="brand-text">
          <span class="brand-name">DigitalLife</span>
          <span class="brand-sub">多智能体操作系统</span>
        </div>
      </div>
    </div>
    <div class="bar-center">
      <StatusDot :status="world.state.connection === 'open' ? 'online' : world.state.connection === 'connecting' ? 'connecting' : 'failed'" :label="connText[world.state.connection]" />
    </div>
    <div class="bar-right">
      <GlowButton variant="secondary" size="sm" @click="navigate({ mode: 'settings' })">系统配置</GlowButton>
      <GlowButton variant="secondary" size="sm" @click="navigate({ mode: 'archive' })">历史卷宗</GlowButton>
      <GlowButton variant="secondary" size="sm" @click="navigate({ mode: 'dashboard' })">总览</GlowButton>
    </div>
  </header>
</template>
<style scoped>
.top-bar { height: 52px; display: flex; align-items: center; justify-content: space-between; padding: 0 var(--space-5); background: rgba(5, 8, 16, 0.8); backdrop-filter: blur(20px); border-bottom: 1px solid var(--glass-border); flex-shrink: 0; z-index: 100; }
.bar-left, .bar-right { display: flex; align-items: center; gap: var(--space-3); }
.bar-center { display: flex; align-items: center; }
.brand-logo { display: flex; align-items: center; gap: var(--space-3); }
.logo-svg { filter: drop-shadow(0 0 8px rgba(0, 217, 255, 0.3)); }
.brand-text { display: flex; flex-direction: column; }
.brand-name { font-family: var(--font-display); font-size: var(--fs-md); font-weight: 600; color: var(--text-primary); letter-spacing: 0.05em; }
.brand-sub { font-size: 10px; color: var(--text-muted); letter-spacing: 0.1em; }
</style>
