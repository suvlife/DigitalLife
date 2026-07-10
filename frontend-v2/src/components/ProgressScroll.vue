<script setup lang="ts">defineProps<{value:number; label?:string}>();</script>
<template><div class="progress-scroll" :aria-label="`${label||'总体进度'} ${value}%`"><div class="progress-head"><span>{{label||'总体进度'}}</span><strong>{{Math.round(value)}}%</strong></div><div class="progress-track"><i :style="{width:`${Math.max(0,Math.min(100,value))}%`}"></i></div></div></template>
