<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { downloadFileUrl, previewFile, type FilePreviewInfo } from '../../api';
import type { ParsedFileInfo } from '../../utils/fileTokens';

const props = defineProps<{
  file: ParsedFileInfo;
}>();

const { t } = useI18n();

const previewOpen = ref(false);
const previewLoading = ref(false);
const previewInfo = ref<FilePreviewInfo | null>(null);
const previewError = ref('');

const fileExtension = computed(() => {
  const dotIndex = props.file.fileName.lastIndexOf('.');
  if (dotIndex < 0) {
    return '';
  }
  return props.file.fileName.slice(dotIndex + 1).toLowerCase();
});

const fileIconClass = computed(() => {
  const ext = fileExtension.value;
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) {
    return 'fa-solid fa-image';
  }
  if (['pdf'].includes(ext)) {
    return 'fa-solid fa-file-pdf';
  }
  if (['docx', 'doc'].includes(ext)) {
    return 'fa-solid fa-file-word';
  }
  if (['xlsx', 'xls', 'csv'].includes(ext)) {
    return 'fa-solid fa-file-excel';
  }
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) {
    return 'fa-solid fa-file-zipper';
  }
  if (['py', 'js', 'ts', 'sql', 'yaml', 'yml', 'json', 'txt', 'md'].includes(ext)) {
    return 'fa-solid fa-file-code';
  }
  return 'fa-solid fa-file';
});

const formattedSize = computed(() => {
  const size = props.file.size;
  if (size === null || size === undefined || !Number.isFinite(size) || size <= 0) {
    return '';
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
});

function handleDownload(): void {
  if (!props.file.path) {
    return;
  }
  window.open(downloadFileUrl(props.file.path), '_blank');
}

async function handlePreview(): Promise<void> {
  if (!props.file.path) {
    return;
  }
  if (previewOpen.value) {
    previewOpen.value = false;
    return;
  }

  previewOpen.value = true;
  previewLoading.value = true;
  previewError.value = '';
  previewInfo.value = null;

  try {
    previewInfo.value = await previewFile(props.file.path);
  } catch (error) {
    previewError.value = t('chat.filePreviewFailed');
    console.error('File preview failed', error);
  } finally {
    previewLoading.value = false;
  }
}

function closePreview(): void {
  previewOpen.value = false;
  previewError.value = '';
  previewInfo.value = null;
}

const previewType = computed(() => previewInfo.value?.preview_type ?? 'unsupported');
</script>

<template>
  <div class="file-card">
    <div class="file-card-main">
      <i :class="fileIconClass" class="file-card-icon" aria-hidden="true"></i>
      <div class="file-card-info">
        <span class="file-card-name" :title="file.fileName">{{ file.fileName }}</span>
        <span v-if="formattedSize" class="file-card-size">{{ formattedSize }}</span>
      </div>
      <div class="file-card-actions">
        <button
          type="button"
          class="file-card-action"
          :disabled="!file.path"
          :title="t('chat.fileDownload')"
          @click="handleDownload"
        >
          <i class="fa-solid fa-download" aria-hidden="true"></i>
        </button>
        <button
          type="button"
          class="file-card-action"
          :disabled="!file.path"
          :title="t('chat.filePreview')"
          @click="handlePreview"
        >
          <i class="fa-solid fa-eye" aria-hidden="true"></i>
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="previewOpen" class="file-preview-modal" @click.self="closePreview">
        <section class="file-preview-dialog">
          <div class="file-preview-head">
            <div class="file-preview-title">
              <i :class="fileIconClass" aria-hidden="true"></i>
              <span>{{ file.fileName }}</span>
            </div>
            <button type="button" class="file-preview-close" @click="closePreview">
              <i class="fa-solid fa-xmark" aria-hidden="true"></i>
            </button>
          </div>
          <div class="file-preview-body">
            <div v-if="previewLoading" class="file-preview-loading">
              {{ t('common.loading') }}
            </div>
            <div v-else-if="previewError" class="file-preview-error">{{ previewError }}</div>
            <template v-else-if="previewInfo">
              <pre
                v-if="previewType === 'text' && previewInfo.text"
                class="file-preview-text"
              >{{ previewInfo.text }}</pre>
              <img
                v-else-if="previewType === 'image' && previewInfo.url"
                :src="previewInfo.url"
                :alt="file.fileName"
                class="file-preview-image"
              />
              <iframe
                v-else-if="previewType === 'pdf' && previewInfo.url"
                :src="previewInfo.url"
                class="file-preview-pdf"
                :title="file.fileName"
              ></iframe>
              <div v-else class="file-preview-unsupported">
                {{ t('chat.filePreviewUnsupported') }}
                <button
                  type="button"
                  class="file-preview-fallback"
                  @click="handleDownload"
                >
                  <i class="fa-solid fa-download" aria-hidden="true"></i>
                  {{ t('chat.fileDownload') }}
                </button>
              </div>
            </template>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.file-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 6px 0;
}

.file-card-main {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--interactive-focus-border) 18%, var(--border-default) 82%);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-panel-muted) 70%, var(--surface-panel) 30%);
  max-width: min(100%, 360px);
}

.file-card-icon {
  font-size: 1.1rem;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.file-card-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.file-card-name {
  color: var(--text-primary);
  font-size: 0.82rem;
  font-weight: 600;
  line-height: 1.3;
  word-break: break-all;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-card-size {
  color: var(--text-secondary);
  font-size: 0.7rem;
  line-height: 1.2;
}

.file-card-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.file-card-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--surface-panel);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.78rem;
  line-height: 1;
  transition:
    border-color 140ms ease,
    background 140ms ease,
    color 140ms ease;
}

.file-card-action:hover:not(:disabled) {
  border-color: var(--interactive-focus-border);
  color: var(--text-primary);
  background: color-mix(in srgb, var(--interactive-selected) 18%, var(--surface-panel) 82%);
}

.file-card-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.file-preview-modal {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(6, 10, 16, 0.5);
  backdrop-filter: blur(6px);
}

.file-preview-dialog {
  width: min(900px, 100%);
  max-height: min(80vh, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-default);
  border-radius: 16px;
  background: var(--surface-overlay);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22);
  overflow: hidden;
}

.file-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.file-preview-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
  font-size: 0.92rem;
  font-weight: 600;
  min-width: 0;
  word-break: break-all;
}

.file-preview-title i {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.file-preview-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
}

.file-preview-close:hover {
  border-color: var(--interactive-focus-border);
  color: var(--text-primary);
}

.file-preview-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.file-preview-loading,
.file-preview-error,
.file-preview-unsupported {
  color: var(--text-secondary);
  font-size: 0.84rem;
  text-align: center;
  padding: 24px 8px;
}

.file-preview-unsupported {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.file-preview-text {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-panel-muted) 80%, var(--surface-panel) 20%);
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 0.8rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.file-preview-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  align-self: center;
  border-radius: 8px;
}

.file-preview-pdf {
  width: 100%;
  height: 70vh;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}

.file-preview-fallback {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--interactive-focus-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--interactive-selected) 18%, var(--surface-panel) 82%);
  color: var(--text-primary);
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}
</style>
