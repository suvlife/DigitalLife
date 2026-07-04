<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

type CustomSelectOption = {
  value: string;
  label: string;
};

const props = defineProps<{
  modelValue: string;
  options: CustomSelectOption[];
  placeholder?: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
}>();

const rootRef = ref<HTMLElement | null>(null);
const open = ref(false);

const selectedOption = computed(() =>
  props.options.find((option) => option.value === props.modelValue) ?? null,
);

const buttonLabel = computed(() => selectedOption.value?.label || props.placeholder || '请选择');

function closeMenu(): void {
  open.value = false;
}

function toggleMenu(): void {
  if (props.disabled) {
    return;
  }
  open.value = !open.value;
}

function selectOption(value: string): void {
  emit('update:modelValue', value);
  closeMenu();
}

function handleDocumentPointerDown(event: PointerEvent): void {
  if (!open.value) {
    return;
  }

  const root = rootRef.value;
  if (!root) {
    return;
  }

  const target = event.target;
  if (target instanceof Node && !root.contains(target)) {
    closeMenu();
  }
}

function handleEscape(event: KeyboardEvent): void {
  if (event.key === 'Escape' && open.value) {
    closeMenu();
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown);
  document.addEventListener('keydown', handleEscape);
});

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown);
  document.removeEventListener('keydown', handleEscape);
});
</script>

<template>
  <div ref="rootRef" class="custom-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      type="button"
      class="custom-select__button"
      :disabled="disabled"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggleMenu"
    >
      <span class="custom-select__label">{{ buttonLabel }}</span>
      <svg class="custom-select__icon" viewBox="0 0 16 16" aria-hidden="true">
        <path d="m4 6 4 4 4-4" />
      </svg>
    </button>

    <div v-if="open" class="custom-select__menu" role="listbox">
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        class="custom-select__option"
        :class="{ 'is-selected': option.value === modelValue }"
        role="option"
        :aria-selected="option.value === modelValue"
        @click="selectOption(option.value)"
      >
        <span>{{ option.label }}</span>
        <span v-if="option.value === modelValue" class="custom-select__check">✓</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.custom-select {
  position: relative;
}

.custom-select__button {
  width: 100%;
  min-height: 48px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 12px;
  background: var(--panel-bg);
  color: var(--text-strong);
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.custom-select__button:hover,
.custom-select__button:focus-visible,
.custom-select.is-open .custom-select__button {
  border-color: var(--focus-border);
}

.custom-select__button:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.custom-select__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.custom-select__icon {
  width: 12px;
  height: 12px;
  flex: 0 0 auto;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.custom-select__menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 24;
  max-height: 240px;
  overflow: auto;
  padding: 6px;
  display: grid;
  gap: 4px;
  border: 1px solid var(--panel-border);
  border-radius: 12px;
  background: color-mix(in srgb, var(--panel-bg) 96%, var(--surface-soft) 4%);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.14);
}

:root[data-theme='light'] .custom-select__menu {
  background: #ffffff;
}

.custom-select__option {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-strong);
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.custom-select__option:hover,
.custom-select__option:focus-visible,
.custom-select__option.is-selected {
  border-color: color-mix(in srgb, var(--focus-border) 42%, transparent);
  background: color-mix(in srgb, var(--selected) 72%, var(--surface-soft) 28%);
}

.custom-select__check {
  color: var(--accent);
  font-size: 0.9rem;
}
</style>
