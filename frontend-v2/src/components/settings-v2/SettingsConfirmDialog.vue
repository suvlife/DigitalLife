<script setup lang="ts">
defineProps<{ open: boolean; title: string; message: string; confirmLabel?: string; busy?: boolean; danger?: boolean }>();
const emit = defineEmits<{ confirm: []; cancel: [] }>();
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="settings-dialog-backdrop" role="presentation" @click.self="emit('cancel')">
      <section class="settings-dialog panel" role="alertdialog" aria-modal="true" :aria-labelledby="`${title}-title`">
        <span class="eyebrow">请再次核验</span>
        <h2 :id="`${title}-title`">{{ title }}</h2>
        <p>{{ message }}</p>
        <div class="settings-actions settings-dialog-actions">
          <button class="quiet-button" type="button" :disabled="busy" @click="emit('cancel')">暂不执行</button>
          <button :class="danger ? 'danger-button' : 'gold-button'" type="button" :disabled="busy" @click="emit('confirm')">
            {{ busy ? '正在执行…' : (confirmLabel || '确认') }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
