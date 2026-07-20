<script setup lang="ts">
const props = withDefaults(defineProps<{
  blur?: 'normal' | 'heavy';
  hover?: boolean;
  glow?: 'none' | 'cyan' | 'teal' | 'amber' | 'red' | 'purple';
  padding?: 'sm' | 'md' | 'lg' | 'none';
}>(), { blur: 'normal', hover: false, glow: 'none', padding: 'md' });

const glowMap = { none: '', cyan: 'glass-glow-cyan', teal: 'glass-glow-teal', amber: 'glass-glow-amber', red: 'glass-glow-red', purple: 'glass-glow-purple' };
const padMap = { none: 'glass-pad-none', sm: 'glass-pad-sm', md: 'glass-pad-md', lg: 'glass-pad-lg' };
</script>
<template>
  <div class="glass-panel" :class="[blur === 'heavy' ? 'glass-blur-heavy' : '', hover ? 'glass-hover' : '', glowMap[glow], padMap[padding]]">
    <slot />
  </div>
</template>
<style scoped>
.glass-panel {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--glass-border);
  border-radius: var(--glass-radius);
  box-shadow: var(--glass-shadow);
  transition: border-color var(--dur-normal) var(--ease-out), box-shadow var(--dur-normal) var(--ease-out), background var(--dur-normal) var(--ease-out);
}
.glass-blur-heavy { backdrop-filter: blur(var(--glass-blur-heavy)); -webkit-backdrop-filter: blur(var(--glass-blur-heavy)); }
.glass-hover:hover { border-color: var(--glass-border-hover); background: var(--glass-bg-hover); }
.glass-pad-none { padding: 0; }
.glass-pad-sm { padding: var(--space-3); }
.glass-pad-md { padding: var(--space-5); }
.glass-pad-lg { padding: var(--space-8); }
.glass-glow-cyan { border-color: rgba(0, 217, 255, 0.3); box-shadow: var(--glow-cyan), var(--glass-shadow); }
.glass-glow-teal { border-color: rgba(0, 255, 179, 0.3); box-shadow: var(--glow-teal), var(--glass-shadow); }
.glass-glow-amber { border-color: rgba(255, 184, 0, 0.3); box-shadow: var(--glow-amber), var(--glass-shadow); }
.glass-glow-red { border-color: rgba(255, 82, 82, 0.3); box-shadow: var(--glow-red), var(--glass-shadow); }
.glass-glow-purple { border-color: rgba(179, 136, 255, 0.3); box-shadow: var(--glow-purple), var(--glass-shadow); }
</style>
