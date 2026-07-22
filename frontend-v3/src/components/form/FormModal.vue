<script setup lang="ts">
import GlassPanel from '../GlassPanel.vue';
import GlowButton from '../GlowButton.vue';
withDefaults(defineProps<{
  open: boolean;
  title?: string;
  width?: string;
  confirmText?: string;
  cancelText?: string;
  confirmDanger?: boolean;
  loading?: boolean;
  hideFooter?: boolean;
}>(), {
  title: '', width: '560px', confirmText: '确定', cancelText: '取消',
  confirmDanger: false, loading: false, hideFooter: false,
});
const emit = defineEmits<{ (e: 'close'): void; (e: 'confirm'): void }>();
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="modal-mask" @click.self="emit('close')">
      <GlassPanel padding="none" glow="cyan" class="modal-box" :style="{ maxWidth: width }">
        <div class="modal-header">
          <h3 class="modal-title">{{ title }}</h3>
          <button class="modal-close" @click="emit('close')">×</button>
        </div>
        <div class="modal-body"><slot /></div>
        <div v-if="!hideFooter" class="modal-footer">
          <slot name="footer">
            <GlowButton variant="secondary" size="sm" @click="emit('close')">{{ cancelText }}</GlowButton>
            <GlowButton :variant="confirmDanger ? 'danger' : 'primary'" size="sm" :loading="loading" @click="emit('confirm')">{{ confirmText }}</GlowButton>
          </slot>
        </div>
      </GlassPanel>
    </div>
  </Teleport>
</template>
<style scoped>
.modal-mask {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
  animation: fade-in var(--dur-fast); padding: var(--space-4);
}
.modal-box { width: 100%; max-height: 88vh; display: flex; flex-direction: column; animation: fade-in-up var(--dur-normal) var(--ease-out); }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--glass-border); }
.modal-title { font-size: var(--fs-md); font-weight: 600; color: var(--text-primary); margin: 0; }
.modal-close { background: none; border: none; color: var(--text-muted); font-size: 22px; cursor: pointer; line-height: 1; padding: 0 4px; }
.modal-close:hover { color: var(--text-primary); }
.modal-body { padding: var(--space-5); overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: var(--space-4); }
.modal-footer { display: flex; justify-content: flex-end; gap: var(--space-3); padding: var(--space-4) var(--space-5); border-top: 1px solid var(--glass-border); }
</style>
