<script setup lang="ts">import { computed } from 'vue';import { world } from '../store/world';const text=computed(()=>({open:'江湖传讯畅通',connecting:'正在接通信鸽',closed:'传讯暂断 · 自动重连',error:'传讯遇阻 · 自动重连'}[world.state.connection]));</script>
<template><div class="connection-pill" :class="world.state.connection" role="status"><span aria-hidden="true"></span>{{ text }}</div></template>
