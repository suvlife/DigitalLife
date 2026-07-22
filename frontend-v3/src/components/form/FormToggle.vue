<script setup lang="ts">
withDefaults(defineProps<{
  modelValue: boolean;
  label?: string;
  disabled?: boolean;
}>(), { label: '', disabled: false });
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>();
</script>
<template>
  <button
    type="button" class="toggle" :class="{ 'toggle-on': modelValue, 'toggle-disabled': disabled }"
    :disabled="disabled" role="switch" :aria-checked="modelValue"
    @click="emit('update:modelValue', !modelValue)"
  >
    <span class="toggle-track"><span class="toggle-thumb" /></span>
    <span v-if="label" class="toggle-label">{{ label }}</span>
  </button>
</template>
<style scoped>
.toggle { display: inline-flex; align-items: center; gap: 8px; background: none; border: none; cursor: pointer; padding: 0; }
.toggle-track {
  width: 36px; height: 20px; border-radius: 10px; background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--glass-border); position: relative; transition: all var(--dur-fast); flex-shrink: 0;
}
.toggle-thumb {
  position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%;
  background: var(--text-muted); transition: all var(--dur-fast) var(--ease-out);
}
.toggle-on .toggle-track { background: rgba(0, 217, 255, 0.25); border-color: var(--holo-cyan); }
.toggle-on .toggle-thumb { left: 18px; background: var(--holo-cyan); box-shadow: 0 0 6px var(--holo-cyan); }
.toggle-disabled { opacity: 0.5; cursor: not-allowed; }
.toggle-label { font-size: var(--fs-sm); color: var(--text-secondary); }
</style>
