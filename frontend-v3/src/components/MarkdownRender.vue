<script setup lang="ts">
import MarkdownIt from 'markdown-it';
const props = defineProps<{ content: string }>();
const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
</script>
<template>
  <div class="md-render" v-html="md.render(props.content || '')"></div>
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
</style>
