<script setup lang="ts">
import { computed } from 'vue';
import type { Agent,Message } from '../domain/types';
import { speakerName } from '../domain/presentation';
const props=defineProps<{messages:readonly Message[];agents:readonly Agent[]}>();
const emit=defineEmits<{jump:[key:string]}>();
const points=computed(()=>props.messages.map((message,index)=>({
 key:message.id!=null?`message-${message.id}`:`message-${message.senderId}-${index}`,
 name:speakerName(message.senderName,props.agents.find(a=>a.id===message.senderId)),
 time:message.sentAt?new Date(message.sentAt).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):`第 ${index+1} 言`,
 operator:message.senderId<0,
})));
</script>
<template><section v-if="points.length" class="speaker-timeline" aria-label="发言顺序时间轴"><header><b>发言次序</b><small>点击人物或时辰，可直达对应发言</small></header><div class="timeline-scroll"><ol><li v-for="(point,index) in points" :key="point.key" :class="{operator:point.operator}"><button type="button" @click="emit('jump',point.key)"><i>{{index+1}}</i><b>{{point.name}}</b><time>{{point.time}}</time></button></li></ol></div></section></template>
