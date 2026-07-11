<script setup lang="ts">
import { computed } from 'vue';
import type { Activity,Agent,RoomStatus,Task } from '../domain/types';
import { activityDetail,activityNarrative,masterName,priorityText,roomStatusText,taskStatusText,taskTheme } from '../domain/presentation';
const props=defineProps<{tasks:readonly Task[];activities:readonly Activity[];agents:readonly Agent[];initialTopic?:string|null;question?:string;roomStatus?:RoomStatus}>();
const agent=(id:number)=>masterName(props.agents.find(a=>a.id===id),`第 ${id} 位先生`);
const theme=computed(()=>taskTheme(props.tasks,props.initialTopic,props.question));
const recent=computed(()=>[...props.activities].sort((a,b)=>Date.parse(b.startedAt||'')-Date.parse(a.startedAt||'')).slice(0,12));
</script>
<template><aside class="task-sidebar">
  <section class="topic-scroll"><header><h2>本室问道卷</h2><span :class="roomStatus">{{roomStatusText(roomStatus)}}</span></header><p>{{theme}}</p>
    <ul v-if="tasks.length" class="task-list"><li v-for="t in tasks" :key="t.id" :class="t.status.toLowerCase()"><span>{{taskStatusText(t.status)}}</span><b>{{t.title}}</b><small>{{agent(t.assigneeId)}} · {{priorityText(t.priority)}}</small></li></ul>
    <small v-else class="scroll-note">卷上所书，即为本室诸位先生共同参详之题。</small>
  </section>
  <section><h2>堂内动静</h2><ol class="activity-list"><li v-if="!recent.length">诸位先生已入座静候，堂中暂且安然。</li><li v-for="a in recent" :key="a.id"><i :class="a.status"></i><span><b>{{activityNarrative(a,agent(a.agentId))}}</b><small v-if="activityDetail(a)">{{activityDetail(a)}}</small></span></li></ol></section>
</aside></template>
