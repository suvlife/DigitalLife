<script setup lang="ts">
import { ref, watch } from 'vue';
import { auth } from './api/auth';
import ConnectionPill from './components/ConnectionPill.vue';
import { world } from './store/world';
const token=ref(auth.getToken()||'');
watch(()=>auth.state.required,required=>{if(required)token.value=auth.getToken()||'';});
function save(){auth.saveToken(token.value);world.reconnect();void world.retryAfterAuthentication();}
function clear(){auth.clearToken();token.value='';}
</script>
<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="数字人生江湖书院首页"><span class="brand-seal">数</span><span><b>数字人生</b><small>江湖书院 · 多智协作</small></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">诸院</RouterLink><RouterLink to="/archive">卷宗</RouterLink><RouterLink to="/settings">管理台</RouterLink></nav>
      <button v-if="auth.state.hasToken" class="auth-trigger" type="button" @click="auth.requireAuthentication('可在此更新访问 Token')">鉴权</button>
      <ConnectionPill />
    </header>
    <section v-if="auth.state.required" class="auth-panel" role="dialog" aria-modal="true" aria-labelledby="auth-title">
      <form @submit.prevent="save">
        <h2 id="auth-title">访问认证</h2><p>{{auth.state.reason||'请输入访问 Token'}}</p>
        <label>Token<input v-model="token" type="password" autocomplete="current-password" autofocus /></label>
        <div><button type="submit" :disabled="!token.trim()">保存并重试</button><button type="button" @click="clear">清除</button></div>
      </form>
    </section>
    <main id="main-content"><RouterView /></main>
    <footer>DigitalLife V2 · 每一盏灯都对应真实的协作状态</footer>
  </div>
</template>
<style scoped>
.auth-trigger{border:1px solid currentColor;border-radius:999px;background:transparent;padding:.35rem .7rem}.auth-panel{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;background:#1118}.auth-panel form{width:min(28rem,calc(100vw - 2rem));padding:1.5rem;border-radius:1rem;background:#f7f0df;color:#292219;box-shadow:0 1rem 4rem #0008}.auth-panel label{display:grid;gap:.4rem}.auth-panel input{padding:.7rem;border:1px solid #8b765a;border-radius:.4rem}.auth-panel form div{display:flex;gap:.7rem;margin-top:1rem}.auth-panel button{padding:.55rem .9rem}
</style>
