<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue';
import { world } from '../store/world';
import { useViewMode } from '../composables/useViewMode';
import * as api from '../api/client';
import GlassPanel from '../components/GlassPanel.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
import AgentOrb from '../components/AgentOrb.vue';
import MarkdownRender from '../components/MarkdownRender.vue';
const { roomId, navigate } = useViewMode();
const room = computed(() => world.state.rooms.find(r => r.id === roomId.value));
const messages = computed(() => roomId.value ? (world.state.messages[roomId.value] || []) : []);
const members = computed(() => world.state.agents.filter(a => room.value?.agentIds.includes(a.id)));
const runtime = computed(() => roomId.value ? world.state.run?.roomRuns[roomId.value] : undefined);
const text = ref(''); const sending = ref(false); const error = ref('');
const chatEnd = ref<HTMLElement | null>(null);
async function load() { if (roomId.value) { await world.loadRoomMessages(roomId.value).catch(() => {}); await scrollToBottom(); } }
async function scrollToBottom() { await nextTick(); chatEnd.value?.scrollIntoView({ behavior: 'smooth' }); }
async function send() {
  if (!text.value.trim() || sending.value) return;
  sending.value = true; error.value = '';
  try { if (roomId.value) { await world.submitMessage(roomId.value, text.value.trim()); text.value = ''; await scrollToBottom(); } }
  catch (e: any) { error.value = e instanceof Error ? e.message : '发送失败'; }
  finally { sending.value = false; }
}
watch(() => messages.value.length, () => scrollToBottom());
onMounted(load); watch(roomId, load);
</script>
<template>
  <div class="room-view" v-if="room">
    <div class="room-header">
      <GlowButton variant="secondary" size="sm" @click="navigate({ mode: 'team' })">← 返回</GlowButton>
      <div class="room-header-info">
        <h1 class="room-title">{{ room.name }}</h1>
        <StatusDot :status="runtime?.status === 'discussing' ? 'active' : runtime?.status === 'completed' ? 'completed' : 'waiting'" :label="runtime?.activityLabel || '等待中'" />
      </div>
    </div>
    <div class="room-body">
      <!-- 对话流 -->
      <GlassPanel padding="none" class="chat-panel">
        <div class="chat-messages">
          <div v-for="(msg, i) in messages" :key="msg.id ?? i" class="msg-item" :class="{ 'msg-operator': msg.senderId < 0 }">
            <div class="msg-avatar">
              <AgentOrb v-if="msg.senderId > 0" :name="msg.senderName" :size="'sm'" />
              <div v-else class="msg-user-icon">你</div>
            </div>
            <div class="msg-content">
              <div class="msg-meta">
                <span class="msg-sender">{{ msg.senderName }}</span>
                <span class="msg-time">{{ new Date(msg.sentAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span>
              </div>
              <MarkdownRender :content="msg.content" class="msg-text" />
            </div>
          </div>
          <div ref="chatEnd" />
          <div v-if="!messages.length" class="chat-empty">
            <p class="empty-title">本室尚无对话</p>
            <p class="empty-desc">输入问题或补充说明，大师们将根据您的提问展开讨论。</p>
          </div>
        </div>
        <div class="chat-input-area">
          <p v-if="error" class="chat-error">{{ error }}</p>
          <textarea v-model="text" class="chat-input" rows="3" placeholder="输入问题或补充说明，支持 Markdown..." @keydown.ctrl.enter="send"></textarea>
          <div class="chat-input-actions">
            <span class="chat-hint">Ctrl + Enter 发送</span>
            <GlowButton variant="primary" size="sm" :disabled="sending || !text.trim()" :loading="sending">{{ sending ? '发送中' : '发送' }}</GlowButton>
          </div>
        </div>
      </GlassPanel>
    </div>
  </div>
  <div v-else class="loading-state"><GlassPanel padding="lg"><p>正在加载房间...</p></GlassPanel></div>
</template>
<style scoped>
.room-view { height: 100%; display: flex; flex-direction: column; padding: var(--space-4) var(--space-6) var(--space-6); gap: var(--space-4); }
.room-header { display: flex; align-items: center; gap: var(--space-4); flex-shrink: 0; }
.room-header-info { display: flex; align-items: center; gap: var(--space-3); }
.room-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text-primary); margin: 0; }
.room-body { flex: 1; display: flex; overflow: hidden; }
.chat-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.chat-messages { flex: 1; overflow-y: auto; padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-4); }
.msg-item { display: flex; gap: var(--space-3); animation: msg-arrive var(--dur-normal) var(--ease-out); }
.msg-operator { flex-direction: row-reverse; }
.msg-avatar { flex-shrink: 0; }
.msg-user-icon { width: 32px; height: 32px; border-radius: 50%; background: var(--glass-bg-active); border: 1px solid var(--glass-border); display: flex; align-items: center; justify-content: center; font-size: var(--fs-xs); color: var(--holo-cyan); }
.msg-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.msg-operator .msg-content { align-items: flex-end; }
.msg-meta { display: flex; gap: var(--space-2); align-items: center; }
.msg-sender { font-size: var(--fs-xs); font-weight: 500; color: var(--text-secondary); }
.msg-time { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); }
.msg-text { font-size: var(--fs-sm); color: var(--text-primary); line-height: var(--lh-relaxed); max-width: 100%; }
.msg-operator .msg-text { background: var(--glass-bg-active); padding: var(--space-2) var(--space-3); border-radius: var(--glass-radius-sm); border: 1px solid var(--glass-border); }
.chat-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; flex: 1; gap: var(--space-2); }
.empty-title { font-size: var(--fs-md); color: var(--text-muted); }
.empty-desc { font-size: var(--fs-sm); color: var(--text-faint); }
.chat-input-area { padding: var(--space-3) var(--space-4); border-top: 1px solid var(--glass-border); display: flex; flex-direction: column; gap: var(--space-2); }
.chat-error { font-size: var(--fs-xs); color: var(--holo-red); }
.chat-input { width: 100%; resize: none; background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); padding: var(--space-3); color: var(--text-primary); font-family: var(--font-body); font-size: var(--fs-sm); line-height: var(--lh-normal); }
.chat-input:focus { border-color: var(--glass-border-active); box-shadow: var(--glow-cyan); }
.chat-input-actions { display: flex; justify-content: space-between; align-items: center; }
.chat-hint { font-size: var(--fs-xs); color: var(--text-muted); }
.loading-state { padding: var(--space-12); display: flex; justify-content: center; }
</style>
