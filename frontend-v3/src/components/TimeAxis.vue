<script setup lang="ts">
import type { Message, Agent } from '../domain/types';
const props = defineProps<{ messages: readonly Message[]; agents: readonly Agent[] }>();
const emit = defineEmits<{ jump: [key: string] }>();
const agentName = (id: number) => props.agents.find(a => a.id === id)?.name || `Agent ${id}`;
</script>
<template>
  <div class="time-axis" v-if="messages.length">
    <div class="axis-header"><span class="axis-title">发言时间轴</span></div>
    <div class="axis-scroll">
      <div class="axis-line">
        <button v-for="(msg, i) in messages" :key="msg.id || i" class="axis-node" :class="{ 'node-operator': msg.senderId < 0 }" @click="emit('jump', msg.id ? `message-${msg.id}` : `msg-${i}`)">
          <span class="node-dot" :class="{ 'dot-active': msg.senderId > 0 }"></span>
          <span class="node-label">{{ msg.senderId < 0 ? '你' : agentName(msg.senderId) }}</span>
          <span class="node-time">{{ new Date(msg.sentAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span>
        </button>
      </div>
    </div>
  </div>
</template>
<style scoped>
.time-axis { display: flex; flex-direction: column; gap: var(--space-2); }
.axis-header { display: flex; align-items: center; }
.axis-title { font-size: var(--fs-xs); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; }
.axis-scroll { overflow-x: auto; padding: var(--space-2) 0; }
.axis-line { display: flex; align-items: center; gap: var(--space-2); position: relative; }
.axis-line::before { content: ''; position: absolute; top: 50%; left: 0; right: 0; height: 1px; background: var(--glass-border); }
.axis-node { display: flex; flex-direction: column; align-items: center; gap: 2px; background: transparent; border: none; cursor: pointer; padding: 4px 8px; position: relative; z-index: 1; transition: all var(--dur-fast); }
.axis-node:hover { transform: translateY(-2px); }
.node-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); border: 2px solid var(--space-dark); }
.dot-active { background: var(--holo-cyan); box-shadow: 0 0 6px var(--holo-cyan); }
.node-label { font-size: 10px; color: var(--text-muted); white-space: nowrap; }
.node-time { font-size: 9px; color: var(--text-faint); font-family: var(--font-mono); white-space: nowrap; }
.node-operator .node-dot { background: var(--holo-silver); }
</style>
