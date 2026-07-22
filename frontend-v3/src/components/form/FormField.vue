<script setup lang="ts">
withDefaults(defineProps<{
  label?: string;
  hint?: string;
  error?: string;
  required?: boolean;
}>(), { label: '', hint: '', error: '', required: false });
</script>
<template>
  <label class="form-field">
    <span v-if="label" class="field-label">
      {{ label }}<span v-if="required" class="field-required">*</span>
    </span>
    <slot />
    <span v-if="error" class="field-error">{{ error }}</span>
    <span v-else-if="hint" class="field-hint">{{ hint }}</span>
  </label>
</template>
<style scoped>
.form-field { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: var(--fs-sm); font-weight: 500; color: var(--text-secondary); }
.field-required { color: var(--holo-red); margin-left: 2px; }
.field-hint { font-size: var(--fs-xs); color: var(--text-muted); }
.field-error { font-size: var(--fs-xs); color: var(--holo-red); }
</style>
