/**
 * 审计 L11：校验后端返回的 URL 仅允许 http/https 协议，阻断 javascript:/data: 等
 * 可执行脚本的伪协议，用于所有 :href 绑定后端数据的场景。
 * 不安全或无法解析时返回空串（配合 v-if 隐藏链接）。
 */
export function safeExternalUrl(url: string | null | undefined): string {
  if (!url) return '';
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href;
    }
  } catch {
    return '';
  }
  return '';
}
