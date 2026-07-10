<script setup lang="ts">
import ConnectionPill from './components/ConnectionPill.vue';
</script>
<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="数字人生江湖书院首页"><span class="brand-seal">数</span><span><b>数字人生</b><small>江湖书院 · 多智协作</small></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">诸院</RouterLink><RouterLink to="/archive">卷宗</RouterLink><a href="/">管理台</a></nav>
      <ConnectionPill />
    </header>
    <main id="main-content"><RouterView /></main>
    <footer>DigitalLife V2 · 每一盏灯都对应真实的协作状态</footer>
  </div>
</template>
