import { ref } from 'vue';
import { getUsageRealtime, type UsageRealtime } from '../api';
import type { FrontendRealtimeEvent } from './eventNormalizer';
import { subscribeRealtimeEvents } from './wsClient';

/**
 * Module-level singleton store for session-level token usage stats.
 *
 * Mirrors the patterns in runtimeStore.ts: a set of module-level refs exposed
 * directly to consumers, and an internal realtime event subscription that
 * accumulates incremental token updates pushed by the backend.
 */
export const usageCurrentModel = ref<string>('');
export const usageSessionPromptTokens = ref<number>(0);
export const usageSessionCompletionTokens = ref<number>(0);
export const usageSessionTotalTokens = ref<number>(0);
export const usageSessionRequestCount = ref<number>(0);
export const usageLoaded = ref<boolean>(false);

export function applyUsageSnapshot(snapshot: UsageRealtime): void {
  usageCurrentModel.value = snapshot.current_model;
  usageSessionPromptTokens.value = snapshot.session_prompt_tokens;
  usageSessionCompletionTokens.value = snapshot.session_completion_tokens;
  usageSessionTotalTokens.value = snapshot.session_total_tokens;
  usageSessionRequestCount.value = snapshot.session_request_count;
  usageLoaded.value = true;
}

export function applyUsageDelta(payload: {
  model: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
}): void {
  if (payload.model) {
    usageCurrentModel.value = payload.model;
  }
  usageSessionPromptTokens.value += payload.promptTokens;
  usageSessionCompletionTokens.value += payload.completionTokens;
  usageSessionTotalTokens.value += payload.totalTokens;
  usageSessionRequestCount.value += 1;
  usageLoaded.value = true;
}

export async function loadUsageRealtime(): Promise<void> {
  try {
    const snapshot = await getUsageRealtime();
    applyUsageSnapshot(snapshot);
  } catch (error) {
    console.error('Failed to load usage realtime:', error);
  }
}

export function clearUsageStore(): void {
  usageCurrentModel.value = '';
  usageSessionPromptTokens.value = 0;
  usageSessionCompletionTokens.value = 0;
  usageSessionTotalTokens.value = 0;
  usageSessionRequestCount.value = 0;
  usageLoaded.value = false;
}

subscribeRealtimeEvents((event: FrontendRealtimeEvent) => {
  if (event.type !== 'usage_updated') {
    return;
  }
  applyUsageDelta({
    model: event.model,
    promptTokens: event.promptTokens,
    completionTokens: event.completionTokens,
    totalTokens: event.totalTokens,
  });
});
