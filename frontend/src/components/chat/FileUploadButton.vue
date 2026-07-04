<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue';
import { useI18n } from 'vue-i18n';
import { uploadFile } from '../../api';
import { showGlobalSuccessToast } from '../../appUiState';

const props = defineProps<{
  roomId: number | null;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  uploaded: [fileName: string];
}>();

const { t } = useI18n();

const MAX_FILE_SIZE = 50 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [
  'txt', 'md', 'json', 'csv', 'pdf', 'docx', 'xlsx',
  'png', 'jpg', 'gif', 'svg', 'zip', 'py', 'js', 'ts', 'sql', 'yaml',
];

const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(',');

const uploading = ref(false);
const errorMessage = ref('');
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef');

const tooltipText = computed(() => t('chat.fileUploadTooltip', {
  size: '50MB',
  formats: ACCEPTED_EXTENSIONS.join(', '),
}));

function getFileExtension(fileName: string): string {
  const dotIndex = fileName.lastIndexOf('.');
  if (dotIndex < 0) {
    return '';
  }
  return fileName.slice(dotIndex + 1).toLowerCase();
}

function validateFile(file: File): string {
  if (file.size > MAX_FILE_SIZE) {
    return t('chat.fileUploadTooLarge', { size: '50MB' });
  }
  const ext = getFileExtension(file.name);
  if (!ext || !ACCEPTED_EXTENSIONS.includes(ext)) {
    return t('chat.fileUploadUnsupportedFormat');
  }
  return '';
}

function triggerFileInput(): void {
  if (uploading.value || props.disabled) {
    return;
  }
  errorMessage.value = '';
  fileInputRef.value?.click();
}

async function handleFileChange(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  target.value = '';

  if (!file) {
    return;
  }

  if (props.roomId === null) {
    errorMessage.value = t('chat.fileUploadNoRoom');
    return;
  }

  const validationError = validateFile(file);
  if (validationError) {
    errorMessage.value = validationError;
    return;
  }

  uploading.value = true;
  errorMessage.value = '';

  try {
    const response = await uploadFile(props.roomId, file);
    showGlobalSuccessToast(t('chat.fileUploadSuccess', { name: file.name }));
    emit('uploaded', file.name);
    void response;
  } catch (error) {
    errorMessage.value = t('chat.fileUploadFailed');
    console.error('File upload failed', error);
  } finally {
    uploading.value = false;
  }
}
</script>

<template>
  <div class="file-upload-button" :data-tooltip="tooltipText">
    <button
      type="button"
      class="upload-btn"
      :class="{ 'is-uploading': uploading }"
      :disabled="uploading || disabled"
      :aria-label="t('chat.fileUploadLabel')"
      @click="triggerFileInput"
    >
      <i v-if="uploading" class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i>
      <i v-else class="fa-solid fa-paperclip" aria-hidden="true"></i>
    </button>
    <input
      ref="fileInputRef"
      type="file"
      class="file-input"
      :accept="ACCEPT_ATTRIBUTE"
      @change="handleFileChange"
    />
    <span v-if="errorMessage" class="upload-error">{{ errorMessage }}</span>
  </div>
</template>

<style scoped>
.file-upload-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-pill) 88%, var(--surface-panel-muted) 12%);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.82rem;
  line-height: 1;
  transition:
    border-color 140ms ease,
    background 140ms ease,
    color 140ms ease;
}

.upload-btn:hover:not(:disabled) {
  border-color: var(--interactive-focus-border);
  color: var(--text-primary);
  background: color-mix(in srgb, var(--interactive-selected) 18%, var(--surface-panel) 82%);
}

.upload-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.upload-btn.is-uploading {
  opacity: 0.85;
}

.file-input {
  display: none;
}

.upload-error {
  font-size: 0.7rem;
  color: var(--banner-error-text, #ef4444);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-upload-button[data-tooltip]:hover::after {
  content: attr(data-tooltip);
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  width: max-content;
  max-width: min(320px, calc(100vw - 48px));
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--surface-overlay);
  border: 1px solid var(--border-default);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.14);
  color: var(--text-primary);
  font-size: 0.72rem;
  font-weight: 500;
  line-height: 1.35;
  letter-spacing: 0;
  white-space: normal;
  z-index: 30;
  pointer-events: none;
}
</style>
