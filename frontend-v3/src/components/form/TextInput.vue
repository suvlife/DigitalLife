<script setup lang="ts">
withDefaults(defineProps<{
  modelValue: string | number;
  type?: string;
  placeholder?: string;
  disabled?: boolean;
  password?: boolean;
  mono?: boolean;
}>(), { type: 'text', placeholder: '', disabled: false, password: false, mono: false });
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>();
function onInput(e: Event) { emit('update:modelValue', (e.target as HTMLInputElement).value); }
</script>
<template>
  <input
    class="form-input" :class="{ 'input-mono': mono }"
    :type="password ? 'password' : type" :value="modelValue" :placeholder="placeholder"
    :disabled="disabled" @input="onInput"
  />
</template>
<style scoped>
.form-input {
  width: 100%; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
  border-radius: var(--glass-radius-sm); padding: 8px 12px; color: var(--text-primary);
  font-family: var(--font-body); font-size: var(--fs-sm); transition: all var(--dur-fast);
  outline: none; box-sizing: border-box;
}
.form-input:focus { border-color: var(--glass-border-active); box-shadow: var(--glow-cyan); }
.form-input:disabled { opacity: 0.5; cursor: not-allowed; }
.form-input::placeholder { color: var(--text-faint); }
.input-mono { font-family: var(--font-mono); font-size: var(--fs-xs); }
</style>
