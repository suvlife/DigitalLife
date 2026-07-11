<script setup lang="ts">
import { computed,onBeforeUnmount,ref,watch } from 'vue';import { world } from '../store/world';
const visiblyOffline=ref(false);let timer:number|undefined;
watch(()=>world.state.connection,(value)=>{if(timer)clearTimeout(timer);if(value==='open'){visiblyOffline.value=false;return;}if(value==='connecting')return;timer=window.setTimeout(()=>visiblyOffline.value=true,4000);},{immediate:true});
onBeforeUnmount(()=>{if(timer)clearTimeout(timer)});
const display=computed(()=>world.state.connection==='open'?'open':visiblyOffline.value?world.state.connection:'connecting');
const text=computed(()=>({open:'江湖传讯畅通',connecting:'正在接通信鸽',closed:'信鸽绕行中 · 正在续接',error:'传讯遇阻 · 正在另寻路径'}[display.value]));
</script>
<template><div class="connection-pill" :class="display" role="status"><span aria-hidden="true"></span>{{ text }}</div></template>
