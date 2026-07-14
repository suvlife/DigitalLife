<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { getDossierDetail, getDossiers } from '../../api';
import type { DossierDetail, DossierSummary } from '../../types';
import MarkdownContent from '../ui/MarkdownContent.vue';
import SettingsBreadcrumb from './SettingsBreadcrumb.vue';
import type { SettingsBreadcrumbItem } from './types';

const props = defineProps<{
  breadcrumbItems: SettingsBreadcrumbItem[];
  teamId: number | null;
}>();

const emit = defineEmits<{
  navigateBreadcrumb: [key: string];
}>();

const { t } = useI18n();

const dossiers = ref<DossierSummary[]>([]);
const isLoading = ref(false);
const statusText = ref('');

const detailOpen = ref(false);
const detail = ref<DossierDetail | null>(null);
const isLoadingDetail = ref(false);
const detailError = ref('');

function formatDateTime(value?: string | null): string {
  if (!value) {
    return t('common.unknown');
  }
  const normalized = value.includes('T') ? value : value.replace(' ', 'T');
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return value.replace('T', ' ').split('.')[0];
  }
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function dossierTitle(item: DossierSummary): string {
  return item.run.title?.trim() || item.run.query?.trim() || `#${item.run.id}`;
}

async function loadDossiers(): Promise<void> {
  if (props.teamId === null) {
    dossiers.value = [];
    return;
  }
  isLoading.value = true;
  statusText.value = '';
  try {
    dossiers.value = await getDossiers(props.teamId);
  } catch (error) {
    console.error(error);
    statusText.value = t('settings.dossiers.loadFailed');
  } finally {
    isLoading.value = false;
  }
}

async function openDetail(item: DossierSummary): Promise<void> {
  detailOpen.value = true;
  detail.value = null;
  detailError.value = '';
  isLoadingDetail.value = true;
  try {
    detail.value = await getDossierDetail(item.run.id);
  } catch (error) {
    console.error(error);
    detailError.value = t('settings.dossiers.detailLoadFailed');
  } finally {
    isLoadingDetail.value = false;
  }
}

function closeDetail(): void {
  detailOpen.value = false;
  detail.value = null;
}

onMounted(() => {
  void loadDossiers();
});

watch(() => props.teamId, () => {
  void loadDossiers();
});
</script>

<template>
  <section id="dossiers" class="config-section">
    <SettingsBreadcrumb :items="breadcrumbItems" @navigate="emit('navigateBreadcrumb', $event)" />

    <div class="section-intro">
      <div class="section-intro-head">
        <div>
          <p class="section-eyebrow">{{ t('settings.dossiers.eyebrow') }}</p>
          <h3>{{ t('settings.dossiers.title') }}</h3>
        </div>
        <div class="section-intro-actions">
          <span v-if="dossiers.length" class="section-count">
            {{ t('settings.dossiers.count', { count: dossiers.length }) }}
          </span>
          <button type="button" class="secondary-button" :disabled="isLoading" @click="loadDossiers">
            {{ t('settings.dossiers.refresh') }}
          </button>
        </div>
      </div>
      <p class="section-desc">{{ t('settings.dossiers.description') }}</p>
    </div>

    <p v-if="statusText" class="section-status section-status--error">{{ statusText }}</p>
    <p v-if="isLoading" class="section-status">{{ t('settings.dossiers.loading') }}</p>

    <template v-else>
      <div v-if="dossiers.length" class="dossier-list">
        <button
          v-for="item in dossiers"
          :key="item.run.id"
          type="button"
          class="dossier-card"
          @click="openDetail(item)"
        >
          <div class="dossier-main">
            <strong class="dossier-title">{{ dossierTitle(item) }}</strong>
            <div class="dossier-meta">
              <span class="dossier-status">{{ item.run.status }}</span>
              <span
                class="svc-chip"
                :class="item.has_conclusion || item.report_ready ? 'svc-chip--ready' : 'svc-chip--pending'"
              >
                {{ item.has_conclusion || item.report_ready
                  ? t('settings.dossiers.ready')
                  : t('settings.dossiers.pending') }}
              </span>
              <span v-if="item.run.blog_post_url" class="svc-chip svc-chip--blog">
                {{ t('settings.dossiers.blogPublished') }}
              </span>
            </div>
          </div>
          <div class="dossier-side">
            <span class="dossier-time">{{ formatDateTime(item.run.created_at) }}</span>
            <span class="dossier-view">{{ t('settings.dossiers.view') }}</span>
          </div>
        </button>
      </div>

      <p v-else class="section-status">{{ t('settings.dossiers.empty') }}</p>
    </template>

    <!-- 卷宗详情 -->
    <Teleport to="body">
      <div v-if="detailOpen" class="editor-overlay" @click.self="closeDetail">
        <section class="editor-dialog panel scrollbar-thin">
          <header class="editor-head">
            <div class="editor-head-copy">
              <p class="editor-eyebrow">{{ t('settings.dossiers.detailTitle') }}</p>
              <h3>{{ detail ? dossierTitle(detail) : '' }}</h3>
            </div>
            <button type="button" class="ghost-button editor-close" :aria-label="t('common.close')" @click="closeDetail">×</button>
          </header>

          <p v-if="isLoadingDetail" class="section-status">{{ t('settings.dossiers.loading') }}</p>
          <p v-else-if="detailError" class="section-status section-status--error">{{ detailError }}</p>

          <template v-else-if="detail">
            <div class="detail-meta-row">
              <span class="detail-chip">{{ t('settings.dossiers.statusLabel') }}: {{ detail.run.status }}</span>
              <span class="detail-chip">
                {{ t('settings.dossiers.createdLabel') }}: {{ formatDateTime(detail.run.created_at) }}
              </span>
              <a
                v-if="detail.run.blog_post_url"
                :href="detail.run.blog_post_url"
                target="_blank"
                rel="noopener"
                class="detail-chip detail-chip--link"
              >{{ t('settings.dossiers.openBlog') }}</a>
            </div>

            <div v-if="detail.run.query" class="detail-block">
              <p class="detail-label">{{ t('settings.dossiers.question') }}</p>
              <p class="detail-question">{{ detail.run.query }}</p>
            </div>

            <div class="detail-block">
              <p class="detail-label">{{ t('settings.dossiers.conclusion') }}</p>
              <MarkdownContent v-if="detail.content" :content="detail.content" class="detail-content" />
              <p v-else class="section-status">{{ t('settings.dossiers.noConclusion') }}</p>
            </div>
          </template>

          <footer class="editor-actions">
            <button type="button" class="secondary-button" @click="closeDetail">{{ t('common.close') }}</button>
          </footer>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.config-section {
  padding: 12px 0 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-intro-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.section-intro-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-intro h3 {
  margin: 2px 0 0;
  color: var(--text-strong);
}

.section-eyebrow {
  margin: 0;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.68rem;
}

.section-desc {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.5;
}

.section-count {
  color: var(--muted);
  font-size: 0.76rem;
}

.section-status {
  color: var(--muted);
  font-size: 0.86rem;
}

.section-status--error {
  color: var(--danger);
}

.dossier-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dossier-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  background: var(--surface-soft);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 140ms ease, background 140ms ease;
}

.dossier-card:hover {
  border-color: var(--focus-border);
  background: var(--backend-selected-hover, color-mix(in srgb, var(--selected) 52%, var(--surface-soft) 48%));
}

.dossier-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dossier-title {
  color: var(--text-strong);
  font-size: 0.94rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 46vw;
}

.dossier-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.dossier-status {
  color: var(--muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.dossier-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.dossier-time {
  color: var(--hint-text);
  font-size: 0.7rem;
  white-space: nowrap;
}

.dossier-view {
  color: var(--accent);
  font-size: 0.76rem;
}

.svc-chip {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--panel-border);
  background: var(--panel-bg);
  color: var(--muted);
  font-size: 0.68rem;
  white-space: nowrap;
}

.svc-chip--ready {
  border-color: color-mix(in srgb, var(--good) 38%, var(--panel-border) 62%);
  background: color-mix(in srgb, var(--good) 12%, var(--panel-bg) 88%);
  color: var(--good);
}

.svc-chip--pending {
  border-color: color-mix(in srgb, var(--warn) 28%, var(--panel-border) 72%);
  background: color-mix(in srgb, var(--warn) 8%, var(--panel-bg) 92%);
  color: var(--warn);
}

.svc-chip--blog {
  border-color: color-mix(in srgb, var(--accent) 32%, var(--panel-border) 68%);
  background: color-mix(in srgb, var(--accent) 10%, var(--panel-bg) 90%);
  color: var(--accent);
}

.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(6, 10, 16, 0.56);
  backdrop-filter: blur(10px);
}

.editor-dialog {
  width: min(760px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
}

.editor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.editor-head-copy {
  min-width: 0;
}

.editor-eyebrow {
  margin: 0;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.68rem;
}

.editor-head h3 {
  margin: 2px 0 0;
  color: var(--text-strong);
}

.editor-close {
  min-width: 32px;
  height: 32px;
  padding: 0;
  font-size: 1rem;
}

.detail-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.detail-chip {
  font-size: 0.72rem;
  color: var(--muted);
  border: 1px solid var(--panel-border);
  background: var(--panel-bg);
  border-radius: 999px;
  padding: 2px 10px;
}

.detail-chip--link {
  color: var(--accent);
  text-decoration: none;
  border-color: color-mix(in srgb, var(--accent) 32%, var(--panel-border) 68%);
}

.detail-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-label {
  margin: 0;
  color: var(--muted);
  font-size: 0.74rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.detail-question {
  margin: 0;
  color: var(--text-strong);
  line-height: 1.5;
  white-space: pre-wrap;
}

.detail-content {
  border: 1px solid var(--panel-border);
  border-radius: 12px;
  background: var(--panel-bg);
  padding: 12px 14px;
}

.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 780px) {
  .dossier-card {
    flex-direction: column;
    align-items: flex-start;
  }

  .dossier-side {
    align-items: flex-start;
  }

  .dossier-title {
    max-width: 100%;
    white-space: normal;
  }
}
</style>
