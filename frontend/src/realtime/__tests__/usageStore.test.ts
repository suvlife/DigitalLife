import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  applyUsageDelta,
  applyUsageSnapshot,
  clearUsageStore,
  usageCurrentModel,
  usageLoaded,
  usageSessionCompletionTokens,
  usageSessionPromptTokens,
  usageSessionRequestCount,
  usageSessionTotalTokens,
} from '../usageStore';

describe('usageStore', () => {
  beforeEach(() => {
    clearUsageStore();
  });

  afterEach(() => {
    clearUsageStore();
  });

  it('applyUsageSnapshot seeds all fields and marks loaded', () => {
    applyUsageSnapshot({
      current_model: 'gpt-4o',
      session_prompt_tokens: 1000,
      session_completion_tokens: 500,
      session_total_tokens: 1500,
      session_request_count: 7,
    });

    expect(usageCurrentModel.value).toBe('gpt-4o');
    expect(usageSessionPromptTokens.value).toBe(1000);
    expect(usageSessionCompletionTokens.value).toBe(500);
    expect(usageSessionTotalTokens.value).toBe(1500);
    expect(usageSessionRequestCount.value).toBe(7);
    expect(usageLoaded.value).toBe(true);
  });

  it('applyUsageDelta accumulates token counts and increments request count', () => {
    applyUsageSnapshot({
      current_model: 'gpt-4o',
      session_prompt_tokens: 100,
      session_completion_tokens: 50,
      session_total_tokens: 150,
      session_request_count: 1,
    });

    applyUsageDelta({
      model: 'gpt-4o-mini',
      promptTokens: 200,
      completionTokens: 100,
      totalTokens: 300,
    });

    expect(usageCurrentModel.value).toBe('gpt-4o-mini');
    expect(usageSessionPromptTokens.value).toBe(300);
    expect(usageSessionCompletionTokens.value).toBe(150);
    expect(usageSessionTotalTokens.value).toBe(450);
    expect(usageSessionRequestCount.value).toBe(2);
  });

  it('applyUsageDelta keeps the previous model when payload model is empty', () => {
    applyUsageSnapshot({
      current_model: 'gpt-4o',
      session_prompt_tokens: 0,
      session_completion_tokens: 0,
      session_total_tokens: 0,
      session_request_count: 0,
    });

    applyUsageDelta({
      model: '',
      promptTokens: 10,
      completionTokens: 5,
      totalTokens: 15,
    });

    expect(usageCurrentModel.value).toBe('gpt-4o');
  });

  it('clearUsageStore resets all fields', () => {
    applyUsageSnapshot({
      current_model: 'gpt-4o',
      session_prompt_tokens: 100,
      session_completion_tokens: 50,
      session_total_tokens: 150,
      session_request_count: 1,
    });

    clearUsageStore();

    expect(usageCurrentModel.value).toBe('');
    expect(usageSessionPromptTokens.value).toBe(0);
    expect(usageSessionCompletionTokens.value).toBe(0);
    expect(usageSessionTotalTokens.value).toBe(0);
    expect(usageSessionRequestCount.value).toBe(0);
    expect(usageLoaded.value).toBe(false);
  });
});
