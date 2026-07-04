export interface ParsedFileInfo {
  fileName: string;
  path: string;
  size: number | null;
}

/**
 * 解析消息内容中的文件标记。
 *
 * 支持以下格式（按优先级匹配）：
 * 1. `[文件:PATH]FILENAME|SIZE`   例如 `[文件:uploads/2024/01/a.txt]a.txt|1024`
 * 2. `[文件:PATH]FILENAME`         例如 `[文件:uploads/2024/01/a.txt]a.txt`
 * 3. `[文件]FILENAME|PATH|SIZE`    例如 `[文件]a.txt|uploads/2024/01/a.txt|1024`
 * 4. `[文件]FILENAME|PATH`         例如 `[文件]a.txt|uploads/2024/01/a.txt`
 * 5. `[文件](PATH "FILENAME")`     markdown 风格
 *
 * PATH 中可能包含 URL 编码字符，按原样使用。
 */
const FILE_TOKEN_PATTERNS: RegExp[] = [
  // [文件:PATH]FILENAME|SIZE
  /\[文件:([^\]]+)\]([^\[\]|]+?)\|(\d+(?:\.\d+)?)/g,
  // [文件:PATH]FILENAME
  /\[文件:([^\]]+)\]([^\[\]]+)/g,
  // [文件]FILENAME|PATH|SIZE
  /\[文件\]([^|\[\]]+?)\|([^|\[\]]+?)\|(\d+(?:\.\d+)?)/g,
  // [文件]FILENAME|PATH
  /\[文件\]([^|\[\]]+?)\|([^|\[\]]+)/g,
  // [文件](PATH "FILENAME")
  /\[文件\]\(([^)\s]+)\s+"([^"]+)"/g,
];

export function parseFileTokens(content: string): ParsedFileInfo[] {
  if (!content || !content.includes('[文件')) {
    return [];
  }

  const files: ParsedFileInfo[] = [];
  const consumedRanges: Array<[number, number]> = [];

  function isConsumed(start: number, end: number): boolean {
    return consumedRanges.some(([s, e]) => start < e && end > s);
  }

  for (const pattern of FILE_TOKEN_PATTERNS) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(content)) !== null) {
      const matchStart = match.index;
      const matchEnd = match.index + match[0].length;
      if (isConsumed(matchStart, matchEnd)) {
        continue;
      }
      consumedRanges.push([matchStart, matchEnd]);

      let fileName = '';
      let path = '';
      let size: number | null = null;

      if (pattern === FILE_TOKEN_PATTERNS[0]) {
        path = match[1].trim();
        fileName = match[2].trim();
        size = Number(match[3]);
      } else if (pattern === FILE_TOKEN_PATTERNS[1]) {
        path = match[1].trim();
        fileName = match[2].trim();
      } else if (pattern === FILE_TOKEN_PATTERNS[2]) {
        fileName = match[1].trim();
        path = match[2].trim();
        size = Number(match[3]);
      } else if (pattern === FILE_TOKEN_PATTERNS[3]) {
        fileName = match[1].trim();
        path = match[2].trim();
      } else if (pattern === FILE_TOKEN_PATTERNS[4]) {
        path = match[1].trim();
        fileName = match[2].trim();
      }

      if (fileName && path) {
        files.push({
          fileName,
          path,
          size: size !== null && Number.isFinite(size) && size > 0 ? size : null,
        });
      }
    }
  }

  return files;
}

/**
 * 从消息内容中移除文件标记，返回剩余的纯文本内容。
 */
export function stripFileTokens(content: string): string {
  if (!content || !content.includes('[文件')) {
    return content;
  }

  let result = content;
  for (const pattern of FILE_TOKEN_PATTERNS) {
    result = result.replace(pattern, '');
  }
  return result.replace(/\s{2,}/g, ' ').trim();
}
