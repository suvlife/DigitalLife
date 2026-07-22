<script setup lang="ts">
import { computed, ref } from 'vue';
import MarkdownIt from 'markdown-it';
import { downloadFile, fileDownloadUrl } from '../api/client';

const props = withDefaults(defineProps<{ content: string; teamId?: number | null }>(), { teamId: null });
const downloadError = ref('');

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
const fallbackLinkOpen = md.renderer.rules.link_open;
md.renderer.rules.link_open = (tokens: any[], idx: number, options: any, env: any, self: any) => {
  tokens[idx].attrSet('target', '_blank');
  tokens[idx].attrSet('rel', 'noopener noreferrer');
  return fallbackLinkOpen ? fallbackLinkOpen(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options);
};

// 注入 v-html 的所有插值必须转义/编码——path 经 fileDownloadUrl 的 encodeURIComponent 编码，
// name/size 经 escaped()/Number 处理。改动此模板时务必维持该不变量，否则引入 XSS。
const escaped = (value: string) => value.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] || c));

const html = computed(() => {
  const source = props.content || '';
  const rendered = md.render(source);
  if (props.teamId == null) return rendered;
  // [文件:uploads/xxx]文件名|字节数 → 可下载文件卡片
  const token = /\[文件:([^\]]+)\]([^|\n]+)(?:\|([\d.]+))?/g;
  return rendered.replace(token, (_all: string, path: string, name: string, size?: string) =>
    `<a class="file-token" href="${fileDownloadUrl(path, props.teamId!)}" data-path="${escaped(path)}" target="_blank" rel="noopener"><b>卷</b><span>${escaped(name.trim())}</span>${size ? `<small>${Math.max(1, Math.round(Number(size) / 1024))}KB</small>` : ''}</a>`);
});

async function handleClick(event: MouseEvent) {
  const target = (event.target as HTMLElement).closest<HTMLAnchorElement>('a.file-token');
  if (!target || props.teamId == null) return;
  event.preventDefault();
  downloadError.value = '';
  try { await downloadFile(String(target.dataset.path || ''), props.teamId); }
  catch (error) { downloadError.value = error instanceof Error ? error.message : '文件下载失败'; }
}
</script>

<template>
  <div class="md-wrapper">
    <div class="md-render" v-html="html" @click="handleClick"></div>
    <p v-if="downloadError" class="file-download-error" role="alert">{{ downloadError }}</p>
  </div>
</template>

<style scoped>
.md-render { word-break: break-word; }
.md-render :deep(h1) { font-size: var(--fs-lg); font-weight: 600; margin: var(--space-3) 0 var(--space-2); color: var(--text-primary); }
.md-render :deep(h2) { font-size: var(--fs-md); font-weight: 600; margin: var(--space-3) 0 var(--space-2); color: var(--text-primary); }
.md-render :deep(h3) { font-size: var(--fs-base); font-weight: 600; margin: var(--space-2) 0 var(--space-1); color: var(--text-secondary); }
.md-render :deep(p) { margin: var(--space-1) 0; line-height: var(--lh-relaxed); }
.md-render :deep(ul), .md-render :deep(ol) { margin: var(--space-1) 0; padding-left: var(--space-5); }
.md-render :deep(li) { margin: 2px 0; }
.md-render :deep(code) { font-family: var(--font-mono); font-size: 0.9em; background: rgba(0, 217, 255, 0.08); padding: 1px 4px; border-radius: 3px; color: var(--holo-cyan); }
.md-render :deep(pre) { background: rgba(0, 0, 0, 0.3); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); padding: var(--space-3); overflow-x: auto; margin: var(--space-2) 0; }
.md-render :deep(pre code) { background: none; color: var(--text-primary); padding: 0; }
.md-render :deep(blockquote) { border-left: 3px solid var(--holo-cyan); padding-left: var(--space-3); margin: var(--space-2) 0; color: var(--text-secondary); }
.md-render :deep(table) { border-collapse: collapse; margin: var(--space-2) 0; width: 100%; }
.md-render :deep(th), .md-render :deep(td) { border: 1px solid var(--glass-border); padding: var(--space-2); font-size: var(--fs-sm); }
.md-render :deep(th) { background: rgba(0, 217, 255, 0.05); color: var(--text-primary); }
.md-render :deep(a) { color: var(--holo-cyan); }
.md-render :deep(strong) { color: var(--text-primary); font-weight: 600; }
/* 文件下载卡片 */
.md-render :deep(a.file-token) {
  display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; margin: 4px 0;
  background: rgba(0, 217, 255, 0.06); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm);
  color: var(--text-primary); text-decoration: none; font-size: var(--fs-sm); transition: all var(--dur-fast);
}
.md-render :deep(a.file-token:hover) { border-color: var(--glass-border-active); background: rgba(0, 217, 255, 0.12); box-shadow: var(--glow-cyan); }
.md-render :deep(a.file-token b) { color: var(--holo-cyan); font-size: var(--fs-xs); border: 1px solid var(--glass-border-active); border-radius: 3px; padding: 0 4px; }
.md-render :deep(a.file-token small) { color: var(--text-muted); font-size: var(--fs-xs); }
.file-download-error { color: var(--holo-red); font-size: var(--fs-xs); margin-top: 4px; }
</style>
