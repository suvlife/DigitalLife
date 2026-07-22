<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue';
import { world } from '../store/world';
import { useViewMode } from '../composables/useViewMode';
import { npcStatusFromActivity } from '../domain/status';
import * as api from '../api/client';
import GlassPanel from '../components/GlassPanel.vue';
import GlowButton from '../components/GlowButton.vue';
import StatusDot from '../components/StatusDot.vue';
import AgentOrb from '../components/AgentOrb.vue';
import MarkdownRender from '../components/MarkdownRender.vue';
import TimeAxis from '../components/TimeAxis.vue';
import SpeakerProgress from '../components/SpeakerProgress.vue';
import RunProgress from '../components/RunProgress.vue';
import FileUpload from '../components/FileUpload.vue';

const { roomId, navigate } = useViewMode();
const room = computed(() => world.state.rooms.find(r => r.id === roomId.value));
const team = computed(() => world.state.team);
const messages = computed(() => roomId.value ? (world.state.messages[roomId.value] || []) : []);
const members = computed(() => world.state.agents.filter(a => room.value?.agentIds.includes(a.id)));
const runtime = computed(() => roomId.value ? world.state.run?.roomRuns[roomId.value] : undefined);
const run = computed(() => world.state.run);
const activities = computed(() => world.state.activities.filter(a => a.roomId === roomId.value || room.value?.agentIds.includes(a.agentId)));
const isRootRoom = computed(() => run.value?.rootRoomId === roomId.value);
const runFinished = computed(() => ['completed', 'partial_failed', 'failed', 'cancelled'].includes(String(run.value?.phase)));
const finalAnswer = computed(() => run.value?.finalAnswer || '');
const showFinalAnswer = ref(false);

const text = ref('');
const sending = ref(false);
const sendStatus = ref<'idle' | 'sending' | 'success' | 'error'>('idle');
const error = ref('');
const chatEnd = ref<HTMLElement | null>(null);
const chatMessages = ref<HTMLElement | null>(null);
const userScrolledUp = ref(false);
const showNewTopic = computed(() => isRootRoom.value && runFinished.value);

async function load() {
  if (roomId.value) {
    await world.loadRoomMessages(roomId.value).catch(() => {});
    await scrollToBottom();
  }
}

async function scrollToBottom() {
  if (userScrolledUp.value) return;
  await nextTick();
  chatEnd.value?.scrollIntoView({ behavior: 'smooth' });
}

function onChatScroll(e: Event) {
  const el = e.target as HTMLElement;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
  userScrolledUp.value = !atBottom;
}

async function send() {
  if (!text.value.trim() || sending.value || !roomId.value) return;
  sending.value = true;
  sendStatus.value = 'sending';
  error.value = '';
  try {
    await world.submitMessage(roomId.value, text.value.trim());
    text.value = '';
    sendStatus.value = 'success';
    userScrolledUp.value = false;
    await scrollToBottom();
    setTimeout(() => sendStatus.value = 'idle', 2000);
  } catch (e: any) {
    sendStatus.value = 'error';
    error.value = e instanceof Error ? e.message : '发送失败';
  } finally {
    sending.value = false;
  }
}

async function startNewDiscussion() {
  if (!roomId.value) return;
  try {
    await world.startNewSession(roomId.value);
    text.value = '';
    error.value = '';
    showFinalAnswer.value = false;
    await scrollToBottom();
  } catch (e: any) {
    error.value = e instanceof Error ? e.message : '发起新讨论失败';
  }
}

function jumpToMessage(key: string) {
  nextTick(() => {
    document.getElementById(key)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    document.getElementById(key)?.classList.add('msg-highlight');
    setTimeout(() => document.getElementById(key)?.classList.remove('msg-highlight'), 1800);
  });
}

/** 消息发送者名字：优先消息自带，缺失时从成员列表回退，保证对话中始终显示名字 */
function senderNameFor(senderId: number): string {
  if (senderId < 0) return '你';
  const agent = world.state.agents.find((a) => a.id === senderId);
  return agent?.name || '';
}

/** 消息发送者的实时状态（用于对话内头像状态符号） */
function senderStatusFor(senderId: number): 'idle' | 'thinking' | 'speaking' | 'working' | 'completed' {
  if (senderId <= 0) return 'idle';
  const latest = activities.value
    .filter((a) => a.agentId === senderId)
    .sort((x, y) => Date.parse(y.startedAt || '') - Date.parse(x.startedAt || ''))[0];
  if (latest) {
    const s = npcStatusFromActivity(latest);
    if (s === 'thinking' || s === 'speaking' || s === 'working' || s === 'completed') return s;
  }
  // 已发言的大师在对话中显示「已发言」标记
  return runtime.value?.currentAgentId === senderId ? 'speaking' : 'completed';
}

/** 时间格式化：对齐当前时区，无效时间回退占位 */
function formatTime(sentAt: string): string {
  if (!sentAt) return '';
  const d = new Date(sentAt);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

/** 房间是否可重试：FAILED 或 COMPLETED（且 Run 未取消） */
const canRetry = computed(() => {
  const rs = runtime.value?.status;
  const runPhase = run.value?.phase;
  return (rs === 'failed' || rs === 'completed') && runPhase !== 'cancelled';
});
const retrying = ref(false);
async function retryRoom() {
  if (!roomId.value || !run.value || retrying.value) return;
  if (!window.confirm('重试本室讨论？将保留上一轮发言供参考，大师们重新贡献一轮。')) return;
  retrying.value = true;
  try {
    await api.retryRoom(run.value.id, roomId.value);
    await world.loadRoomMessages(roomId.value).catch(() => {});
  } catch (e: any) {
    window.alert(e?.message || '重试失败');
  } finally { retrying.value = false; }
}

/** 判断消息是否为"上一轮"分隔线（系统消息 + ━━━ 开头） */
function isSeparator(content: string): boolean {
  return content.startsWith('━━━');
}

/** 最后一条分隔线的索引：其前的消息属于"上一轮"（灰显） */
const lastSeparatorIdx = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (isSeparator(messages.value[i].content)) return i;
  }
  return -1;
});
function isPrevRound(i: number): boolean {
  return lastSeparatorIdx.value >= 0 && i < lastSeparatorIdx.value;
}

watch(() => messages.value.length, () => { if (!userScrolledUp.value) scrollToBottom(); });
onMounted(load);
watch(roomId, () => { userScrolledUp.value = false; load(); });
</script>

<template>
  <div class="room-view" v-if="room">
    <!-- 顶部：房间头 + 操作 -->
    <div class="room-header">
      <GlowButton variant="secondary" size="sm" @click="navigate({ mode: 'team' })">← 返回</GlowButton>
      <div class="room-header-info">
        <h1 class="room-title">{{ room.name }}</h1>
        <StatusDot :status="runtime?.status === 'discussing' ? 'active' : runtime?.status === 'completed' ? 'completed' : 'waiting'" :label="runtime?.activityLabel || '等待中'" />
      </div>
      <GlowButton v-if="isRootRoom" variant="primary" size="sm" @click="startNewDiscussion">发起新讨论</GlowButton>
      <GlowButton v-if="canRetry" variant="secondary" size="sm" :loading="retrying" @click="retryRoom">重试本室</GlowButton>
    </div>

    <!-- 发言进度 -->
    <SpeakerProgress :members="members" :messages="messages" :activities="activities" :current-agent-id="runtime?.currentAgentId ?? null" :room-status="runtime?.status || 'waiting'" />

    <!-- 发言人时间轴 -->
    <TimeAxis :messages="messages" :agents="members" @jump="jumpToMessage" />

    <!-- 最终答案（可展开） -->
    <GlassPanel v-if="finalAnswer" padding="md" glow="purple" class="final-answer-panel">
      <div class="fa-header" @click="showFinalAnswer = !showFinalAnswer">
        <span class="fa-title">最终结论</span>
        <span class="fa-toggle">{{ showFinalAnswer ? '收起 ▲' : '展开 ▼' }}</span>
      </div>
      <div v-if="showFinalAnswer" class="fa-content">
        <MarkdownRender :content="finalAnswer" :team-id="team?.id ?? null" />
      </div>
    </GlassPanel>

    <!-- 对话流 -->
    <div class="room-body">
      <GlassPanel padding="none" class="chat-panel">
        <div class="chat-messages" ref="chatMessages" @scroll="onChatScroll">
          <template v-for="(msg, i) in messages" :key="msg.id ?? i">
            <!-- 上一轮分隔线 -->
            <div v-if="isSeparator(msg.content)" class="round-separator">
              <span class="round-sep-text">{{ msg.content }}</span>
            </div>
            <!-- 普通消息（上一轮的灰显） -->
            <div v-else :id="msg.id ? `message-${msg.id}` : `msg-${i}`" class="msg-item" :class="{ 'msg-operator': msg.senderId < 0, 'msg-prev-round': isPrevRound(i) }">
              <div class="msg-avatar">
                <AgentOrb v-if="msg.senderId > 0" :name="senderNameFor(msg.senderId)" :size="'sm'" :status="senderStatusFor(msg.senderId)" />
                <div v-else class="msg-user-icon">你</div>
              </div>
              <div class="msg-content">
                <div class="msg-meta">
                  <span class="msg-sender">{{ senderNameFor(msg.senderId) || (msg.senderId < 0 ? '你' : `大师 ${msg.senderId}`) }}</span>
                  <span class="msg-time">{{ formatTime(msg.sentAt) }}</span>
                </div>
                <MarkdownRender :content="msg.content" class="msg-text" :team-id="team?.id ?? null" />
              </div>
            </div>
          </template>
          <div ref="chatEnd" />
          <div v-if="!messages.length" class="chat-empty">
            <p class="empty-title">本室尚无对话</p>
            <p class="empty-desc">输入问题或补充说明，大师们将根据您的提问展开讨论。</p>
          </div>
        </div>
        <div class="chat-input-area">
          <div v-if="sendStatus === 'success'" class="send-success">消息已发送，大师们正在响应...</div>
          <p v-if="error" class="chat-error">{{ error }}</p>
          <textarea v-model="text" class="chat-input" rows="3" placeholder="输入问题或补充说明，支持 Markdown..." @keydown.ctrl.enter="send"></textarea>
          <div class="chat-input-actions">
            <FileUpload :room-id="roomId!" :disabled="sending" @uploaded="load" />
            <span class="chat-hint">Ctrl + Enter 发送</span>
            <GlowButton variant="primary" size="sm" :disabled="sending || !text.trim()" :loading="sending">
              {{ sending ? '发送中' : '发送' }}
            </GlowButton>
          </div>
        </div>
      </GlassPanel>
    </div>

    <!-- 运行进度 -->
    <RunProgress :run="run" :room-id="roomId || 0" />
  </div>
  <div v-else class="loading-state"><GlassPanel padding="lg"><p>正在加载房间...</p></GlassPanel></div>
</template>

<style scoped>
.room-view { height: 100%; display: flex; flex-direction: column; padding: var(--space-3) var(--space-6) var(--space-4); gap: var(--space-3); overflow-y: auto; }
.room-header { display: flex; align-items: center; gap: var(--space-4); flex-shrink: 0; }
.room-header-info { display: flex; align-items: center; gap: var(--space-3); flex: 1; }
.room-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text-primary); margin: 0; }
.room-body { flex: 1; display: flex; overflow: hidden; min-height: 300px; }
.chat-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.chat-messages { flex: 1; overflow-y: auto; padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-4); }
.msg-item { display: flex; gap: var(--space-3); animation: msg-arrive var(--dur-normal) var(--ease-out); transition: background var(--dur-fast); border-radius: var(--glass-radius-sm); padding: var(--space-2); }
.msg-highlight { background: rgba(0, 217, 255, 0.06); border: 1px solid var(--glass-border-active); }
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
/* 上一轮分隔线 */
.round-separator { display: flex; align-items: center; justify-content: center; padding: var(--space-2) 0; margin: var(--space-1) 0; border-top: 1px dashed rgba(180,120,255,0.3); border-bottom: 1px dashed rgba(180,120,255,0.3); }
.round-sep-text { font-size: var(--fs-xs); color: var(--holo-purple); font-style: italic; letter-spacing: 0.5px; text-align: center; }
/* 上一轮消息灰显 */
.msg-prev-round { opacity: 0.45; filter: saturate(0.4); }
.chat-input-area { padding: var(--space-3) var(--space-4); border-top: 1px solid var(--glass-border); display: flex; flex-direction: column; gap: var(--space-2); }
.chat-error { font-size: var(--fs-xs); color: var(--holo-red); }
.send-success { font-size: var(--fs-xs); color: var(--holo-teal); animation: fade-in var(--dur-fast); }
.chat-input { width: 100%; resize: none; background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); padding: var(--space-3); color: var(--text-primary); font-family: var(--font-body); font-size: var(--fs-sm); line-height: var(--lh-normal); }
.chat-input:focus { border-color: var(--glass-border-active); box-shadow: var(--glow-cyan); }
.chat-input-actions { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); }
.chat-hint { font-size: var(--fs-xs); color: var(--text-muted); }
.final-answer-panel { cursor: pointer; }
.fa-header { display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
.fa-title { font-size: var(--fs-sm); font-weight: 600; color: var(--holo-purple); }
.fa-toggle { font-size: var(--fs-xs); color: var(--text-muted); }
.fa-content { margin-top: var(--space-3); max-height: 400px; overflow-y: auto; }
.loading-state { padding: var(--space-12); display: flex; justify-content: center; }
</style>
