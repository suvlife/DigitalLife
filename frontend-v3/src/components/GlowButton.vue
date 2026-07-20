<script setup lang="ts">
const props = withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  loading?: boolean;
}>(), { variant: 'secondary', size: 'md', disabled: false, loading: false });
</script>
<template>
  <button class="glow-btn" :class="[`btn-${variant}`, `btn-${size}`, { 'btn-disabled': disabled || loading }]" :disabled="disabled || loading">
    <span v-if="loading" class="btn-spinner"></span>
    <slot />
  </button>
</template>
<style scoped>
.glow-btn {
  font-family: var(--font-body); font-weight: 500;
  border: none; border-radius: var(--glass-radius-sm);
  cursor: pointer; transition: all var(--dur-fast) var(--ease-out);
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  white-space: nowrap; outline: none;
}
.btn-sm { font-size: var(--fs-xs); padding: 5px 12px; }
.btn-md { font-size: var(--fs-sm); padding: 8px 18px; }
.btn-lg { font-size: var(--fs-base); padding: 12px 24px; }
/* 主按钮 - 发光青 */
.btn-primary {
  background: linear-gradient(135deg, rgba(0, 217, 255, 0.15), rgba(0, 217, 255, 0.05));
  border: 1px solid rgba(0, 217, 255, 0.4); color: var(--holo-cyan);
  box-shadow: 0 0 12px rgba(0, 217, 255, 0.15);
}
.btn-primary:hover { background: linear-gradient(135deg, rgba(0, 217, 255, 0.25), rgba(0, 217, 255, 0.1)); box-shadow: var(--glow-cyan); border-color: var(--holo-cyan); }
/* 次按钮 - 透明描边 */
.btn-secondary {
  background: rgba(255, 255, 255, 0.03); border: 1px solid var(--glass-border); color: var(--text-secondary);
}
.btn-secondary:hover { border-color: var(--glass-border-hover); color: var(--text-primary); background: rgba(255, 255, 255, 0.05); }
/* 危险按钮 - 克制红 */
.btn-danger {
  background: rgba(255, 82, 82, 0.08); border: 1px solid rgba(255, 82, 82, 0.3); color: var(--holo-red);
}
.btn-danger:hover { background: rgba(255, 82, 82, 0.15); border-color: var(--holo-red); box-shadow: var(--glow-red); }
.btn-disabled { opacity: 0.4; cursor: not-allowed; }
.btn-disabled:hover { box-shadow: none; transform: none; }
.btn-spinner {
  width: 12px; height: 12px; border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
