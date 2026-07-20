<script setup lang="ts">
import { computed, ref } from 'vue';
import { uploadFile, ApiError } from '../api/client';
import GlowButton from './GlowButton.vue';

const props = withDefaults(defineProps<{
  roomId: number;
  disabled?: boolean;
}>(), { disabled: false });

const emit = defineEmits<{
  (e: 'uploaded'): void;
}>();

/** 允许上传的文件扩展名 */
const ALLOWED_EXTENSIONS = [
  'txt', 'md', 'json', 'csv', 'py', 'js', 'ts', 'sql', 'yaml', 'yml',
  'docx', 'xlsx', 'pptx', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'zip',
] as const;
/** 文件大小上限 50MB */
const MAX_SIZE = 50 * 1024 * 1024;

const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const progress = ref(0);
const error = ref('');
const dragging = ref(false);
const dragDepth = ref(0);

const accept = computed(() => ALLOWED_EXTENSIONS.map(ext => `.${ext}`).join(','));
const isDisabled = computed(() => props.disabled || uploading.value);

function validate(file: File): string {
  const ext = file.name.split('.').pop()?.toLowerCase() || '';
  if (!ALLOWED_EXTENSIONS.includes(ext as typeof ALLOWED_EXTENSIONS[number])) {
    return `不支持的文件类型: .${ext || '未知'}`;
  }
  if (file.size > MAX_SIZE) {
    return `文件过大: ${(file.size / 1024 / 1024).toFixed(1)}MB，上限 50MB`;
  }
  if (file.size === 0) return '文件为空';
  return '';
}

function pickFile() {
  if (isDisabled.value) return;
  fileInput.value?.click();
}

function onFilePicked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) startUpload(file);
  input.value = '';
}

function onDragEnter(event: DragEvent) {
  if (isDisabled.value) return;
  event.preventDefault();
  dragDepth.value += 1;
  dragging.value = true;
}

function onDragOver(event: DragEvent) {
  if (isDisabled.value) return;
  event.preventDefault();
}

function onDragLeave(event: DragEvent) {
  event.preventDefault();
  dragDepth.value = Math.max(0, dragDepth.value - 1);
  if (dragDepth.value === 0) dragging.value = false;
}

function onDrop(event: DragEvent) {
  event.preventDefault();
  dragDepth.value = 0;
  dragging.value = false;
  if (isDisabled.value) return;
  const file = event.dataTransfer?.files?.[0];
  if (file) startUpload(file);
}

async function startUpload(file: File) {
  error.value = '';
  const invalid = validate(file);
  if (invalid) {
    error.value = invalid;
    return;
  }
  uploading.value = true;
  progress.value = 0;
  // 后端 fetch 无进度回调，用缓动模拟进度提示，完成时定格 100%
  const timer = window.setInterval(() => {
    progress.value = Math.min(90, progress.value + Math.max(1, (90 - progress.value) * 0.08));
  }, 200);
  try {
    const result = await uploadFile(props.roomId, file, `已上传文件: ${file.name}`);
    void result;
    progress.value = 100;
    emit('uploaded');
    window.setTimeout(() => { progress.value = 0; }, 800);
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : (err instanceof Error ? err.message : '上传失败');
    progress.value = 0;
  } finally {
    window.clearInterval(timer);
    uploading.value = false;
  }
}
</script>

<template>
  <div
    class="file-upload"
    :class="{ 'is-dragging': dragging, 'is-uploading': uploading }"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="fileInput"
      type="file"
      class="file-input"
      :accept="accept"
      :disabled="isDisabled"
      @change="onFilePicked"
    />
    <GlowButton
      variant="secondary"
      size="sm"
      :disabled="isDisabled"
      :loading="uploading"
      @click="pickFile"
    >
      <span v-if="!uploading" class="upload-icon">⇪</span>
      {{ uploading ? '上传中…' : '上传文件' }}
    </GlowButton>

    <div v-if="dragging" class="drop-hint">
      <span class="drop-icon">⇪</span>
      <span>释放以上传到房间</span>
      <span class="drop-meta">支持 {{ ALLOWED_EXTENSIONS.length }} 种格式 · 上限 50MB</span>
    </div>

    <div v-if="uploading" class="progress-track" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100">
      <div class="progress-bar" :style="{ width: `${progress}%` }"></div>
    </div>

    <div v-if="error" class="upload-error" role="alert">
      <span class="error-icon">⚠</span>
      <span class="error-text">{{ error }}</span>
      <button class="error-close" type="button" aria-label="关闭" @click="error = ''">×</button>
    </div>
  </div>
</template>

<style scoped>
.file-upload {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border: 1px dashed transparent;
  border-radius: var(--glass-radius-sm);
  padding: 2px;
  transition: border-color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out);
}
.file-upload.is-dragging {
  border-color: var(--holo-cyan);
  background: var(--glass-bg-active);
  box-shadow: var(--glow-cyan);
}
.file-input { display: none; }

.upload-icon {
  font-size: var(--fs-sm);
  color: var(--holo-cyan);
  text-shadow: 0 0 6px rgba(0, 217, 255, 0.5);
}

.drop-hint {
  position: absolute;
  inset: -6px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--glass-border-active);
  border-radius: var(--glass-radius-sm);
  color: var(--text-cyan);
  font-family: var(--font-body);
  font-size: var(--fs-xs);
  pointer-events: none;
  animation: hint-fade-in var(--dur-fast) var(--ease-out);
}
.drop-icon {
  font-size: var(--fs-lg);
  text-shadow: 0 0 10px rgba(0, 217, 255, 0.6);
  animation: icon-float 1.2s var(--ease-in-out) infinite;
}
.drop-meta { color: var(--text-muted); font-size: 10px; }

.progress-track {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -4px;
  height: 3px;
  background: rgba(0, 217, 255, 0.12);
  border-radius: 2px;
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--holo-teal), var(--holo-cyan));
  box-shadow: 0 0 8px rgba(0, 217, 255, 0.6);
  border-radius: 2px;
  transition: width var(--dur-normal) var(--ease-out);
}

.upload-error {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  max-width: 320px;
  padding: 6px 10px;
  background: rgba(255, 82, 82, 0.08);
  border: 1px solid rgba(255, 82, 82, 0.35);
  border-radius: var(--glass-radius-sm);
  box-shadow: var(--glow-red);
  color: var(--holo-red);
  font-family: var(--font-body);
  font-size: var(--fs-xs);
  white-space: nowrap;
  animation: hint-fade-in var(--dur-fast) var(--ease-out);
}
.error-icon { flex-shrink: 0; }
.error-text { overflow: hidden; text-overflow: ellipsis; }
.error-close {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--holo-red-dim);
  cursor: pointer;
  font-size: var(--fs-sm);
  line-height: 1;
  padding: 0 2px;
}
.error-close:hover { color: var(--holo-red); }

@keyframes hint-fade-in {
  from { opacity: 0; transform: translateY(2px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes icon-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}
</style>
