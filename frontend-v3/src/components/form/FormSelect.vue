<script setup lang="ts">
interface Option { value: string | number; label: string }
withDefaults(defineProps<{
  modelValue: string | number;
  options: Option[];
  placeholder?: string;
  disabled?: boolean;
}>(), { placeholder: '请选择', disabled: false });
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>();
function onChange(e: Event) { emit('update:modelValue', (e.target as HTMLSelectElement).value); }
</script>
<template>
  <select class="form-select" :value="modelValue" :disabled="disabled" @change="onChange">
    <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
    <option v-for="opt in options" :key="String(opt.value)" :value="opt.value">{{ opt.label }}</option>
  </select>
</template>
<style scoped>
.form-select {
  width: 100%; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
  border-radius: var(--glass-radius-sm); padding: 8px 12px; color: var(--text-primary);
  font-family: var(--font-body); font-size: var(--fs-sm); transition: all var(--dur-fast);
  outline: none; cursor: pointer; box-sizing: border-box;
}
.form-select:focus { border-color: var(--glass-border-active); box-shadow: var(--glow-cyan); }
.form-select:disabled { opacity: 0.5; cursor: not-allowed; }
.form-select option { background: var(--bg-secondary, #0a1628); color: var(--text-primary); }
</style>
