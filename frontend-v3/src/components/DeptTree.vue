<script setup lang="ts">
import { computed } from 'vue';
import type { DeptTreeNode } from '../api/client';
import AgentOrb from './AgentOrb.vue';

const props = withDefaults(defineProps<{
  node: DeptTreeNode | null;
  depth?: number;
}>(), { depth: 0 });

const hasChildren = computed(() => (props.node?.children?.length ?? 0) > 0);
</script>

<template>
  <div v-if="node" class="dept-node" :style="{ marginLeft: depth > 0 ? 'var(--space-5)' : '0' }">
    <div class="dept-card">
      <div class="dept-head">
        <span class="dept-name">{{ node.name }}</span>
        <span v-if="node.agent_ids?.length" class="dept-count">{{ node.agent_ids.length }} 人</span>
      </div>
      <p v-if="node.responsibility" class="dept-resp">{{ node.responsibility }}</p>
    </div>
    <div v-if="hasChildren" class="dept-children">
      <DeptTree v-for="(child, i) in node.children" :key="child.id ?? i" :node="child" :depth="depth + 1" />
    </div>
  </div>
</template>

<style scoped>
.dept-node { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2); }
.dept-card { background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border); border-left: 2px solid var(--holo-purple); border-radius: var(--glass-radius-sm); padding: var(--space-2) var(--space-3); }
.dept-head { display: flex; align-items: center; gap: var(--space-2); }
.dept-name { font-size: var(--fs-sm); font-weight: 500; color: var(--text-primary); }
.dept-count { font-size: 10px; padding: 0 6px; border-radius: 4px; background: rgba(180,120,255,0.12); color: var(--holo-purple); border: 1px solid rgba(180,120,255,0.3); }
.dept-resp { font-size: var(--fs-xs); color: var(--text-muted); margin: 2px 0 0; }
.dept-children { display: flex; flex-direction: column; }
</style>
