<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import {
  loadUsageRealtime,
  usageCurrentModel,
  usageLoaded,
  usageSessionCompletionTokens,
  usageSessionPromptTokens,
  usageSessionRequestCount,
  usageSessionTotalTokens,
} from '../../realtime/usageStore';

const { t } = useI18n();

const expanded = ref(false);

const model = computed<string>(() => usageCurrentModel.value || t('tokenUsage.unknownModel'));
const promptTokens = computed<number>(() => usageSessionPromptTokens.value);
const completionTokens = computed<number>(() => usageSessionCompletionTokens.value);
const totalTokens = computed<number>(() => usageSessionTotalTokens.value);
const requestCount = computed<number>(() => usageSessionRequestCount.value);
const loaded = computed<boolean>(() => usageLoaded.value);

function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

function toggleExpanded(): void {
  expanded.value = !expanded.value;
}

onMounted(() => {
  // Initial fetch of the snapshot. The singleton store updates reactively
  // when usage_updated events arrive, so we only need to seed the initial
  // value on first mount (or if not yet loaded).
  if (!usageLoaded.value) {
    void loadUsageRealtime();
  }
});
</script>

<template>
  <div
    class="token-status-bar"
    :class="{ 'token-status-bar--expanded': expanded }"
    :aria-expanded="expanded"
    role="button"
    tabindex="0"
    :title="expanded ? t('tokenUsage.collapsed') : t('tokenUsage.expanded')"
    @click="toggleExpanded"
    @keydown.enter.prevent="toggleExpanded"
    @keydown.space.prevent="toggleExpanded"
  >
    <div v-if="!expanded" class="token-status-bar__collapsed">
      <span class="token-status-bar__model" :title="model">{{ model }}</span>
      <span class="token-status-bar__sep" aria-hidden="true">·</span>
      <span class="token-status-bar__total">{{ formatNumber(totalTokens) }}</span>
    </div>

    <div v-else class="token-status-bar__expanded">
      <div class="token-status-bar__head">
        <span class="token-status-bar__head-title">{{ t('tokenUsage.model') }}</span>
        <button
          type="button"
          class="token-status-bar__close"
          :aria-label="t('tokenUsage.collapsed')"
          :title="t('tokenUsage.collapsed')"
          @click.stop="toggleExpanded"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="m4 4 8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>
      <div class="token-status-bar__model-row" :title="model">{{ model }}</div>
      <dl class="token-status-bar__stats">
        <div class="token-status-bar__stat">
          <dt>{{ t('tokenUsage.promptTokens') }}</dt>
          <dd>{{ formatNumber(promptTokens) }}</dd>
        </div>
        <div class="token-status-bar__stat">
          <dt>{{ t('tokenUsage.completionTokens') }}</dt>
          <dd>{{ formatNumber(completionTokens) }}</dd>
        </div>
        <div class="token-status-bar__stat token-status-bar__stat--accent">
          <dt>{{ t('tokenUsage.totalTokens') }}</dt>
          <dd>{{ formatNumber(totalTokens) }}</dd>
        </div>
        <div class="token-status-bar__stat">
          <dt>{{ t('tokenUsage.requestCount') }}</dt>
          <dd>{{ formatNumber(requestCount) }}</dd>
        </div>
      </dl>
      <p v-if="!loaded" class="token-status-bar__hint">{{ t('tokenUsage.noData') }}</p>
    </div>
  </div>
</template>

<style scoped>
.token-status-bar {
  position: fixed;
  bottom: 8px;
  right: 8px;
  z-index: 9999;
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface-panel) 88%, var(--surface-overlay) 12%);
  color: var(--text-primary);
  font-size: 0.72rem;
  line-height: 1.2;
  padding: 4px 12px;
  cursor: pointer;
  user-select: none;
  outline: none;
  box-shadow: var(--shadow-panel);
  backdrop-filter: blur(12px);
  transition:
    border-color 140ms ease,
    background 140ms ease,
    box-shadow 140ms ease,
    border-radius 160ms ease;
}

.token-status-bar:hover,
.token-status-bar:focus-visible {
  border-color: var(--interactive-focus-border);
  box-shadow: var(--shadow-panel), 0 0 0 2px var(--interactive-focus-ring);
}

.token-status-bar--expanded {
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  min-width: 220px;
  border-radius: 14px;
  padding: 10px 12px 12px;
  cursor: default;
}

.token-status-bar--expanded:hover,
.token-status-bar--expanded:focus-visible {
  box-shadow: var(--shadow-panel);
}

.token-status-bar__collapsed {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 320px;
}

.token-status-bar__model {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-weight: 600;
}

.token-status-bar__sep {
  color: var(--text-tertiary);
}

.token-status-bar__total {
  color: color-mix(in srgb, var(--state-info) 82%, var(--text-primary) 18%);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.token-status-bar__expanded {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.token-status-bar__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.token-status-bar__head-title {
  color: var(--text-tertiary);
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.token-status-bar__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0;
  outline: none;
  transition: border-color 140ms ease, background 140ms ease, color 140ms ease;
}

.token-status-bar__close:hover,
.token-status-bar__close:focus-visible {
  border-color: var(--border-subtle);
  background: color-mix(in srgb, var(--interactive-selected) 32%, transparent);
  color: var(--text-primary);
}

.token-status-bar__close svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.token-status-bar__model-row {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-weight: 700;
  font-size: 0.86rem;
}

.token-status-bar__stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  margin: 4px 0 0;
}

.token-status-bar__stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.token-status-bar__stat dt {
  color: var(--text-tertiary);
  font-size: 0.6rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.token-status-bar__stat dd {
  margin: 0;
  color: var(--text-primary);
  font-size: 0.86rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.token-status-bar__stat--accent dt {
  color: color-mix(in srgb, var(--state-info) 78%, var(--text-tertiary) 22%);
}

.token-status-bar__stat--accent dd {
  color: color-mix(in srgb, var(--state-info) 82%, var(--text-primary) 18%);
}

.token-status-bar__hint {
  margin: 4px 0 0;
  color: var(--text-tertiary);
  font-size: 0.66rem;
  text-align: center;
}

:global(html.bp-console-mobile) .token-status-bar {
  font-size: 0.68rem;
  padding: 4px 10px;
}

:global(html.bp-console-mobile) .token-status-bar__model {
  max-width: 120px;
}
</style>
