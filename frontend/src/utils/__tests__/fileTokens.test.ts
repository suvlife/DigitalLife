import { describe, it, expect } from 'vitest';
import { parseFileTokens, stripFileTokens } from '../fileTokens';

describe('fileTokens', () => {
  it('returns empty array for content without file markers', () => {
    expect(parseFileTokens('hello world')).toEqual([]);
  });

  it('parses [文件:PATH]FILENAME|SIZE format', () => {
    const result = parseFileTokens('[文件:uploads/a.txt]a.txt|1024');
    expect(result).toEqual([{ fileName: 'a.txt', path: 'uploads/a.txt', size: 1024 }]);
  });

  it('parses [文件:PATH]FILENAME format', () => {
    const result = parseFileTokens('[文件:uploads/a.txt]a.txt');
    expect(result).toEqual([{ fileName: 'a.txt', path: 'uploads/a.txt', size: null }]);
  });

  it('parses [文件]FILENAME|PATH|SIZE format', () => {
    const result = parseFileTokens('[文件]a.txt|uploads/a.txt|2048');
    expect(result).toEqual([{ fileName: 'a.txt', path: 'uploads/a.txt', size: 2048 }]);
  });

  it('parses [文件]FILENAME|PATH format', () => {
    const result = parseFileTokens('[文件]a.txt|uploads/a.txt');
    expect(result).toEqual([{ fileName: 'a.txt', path: 'uploads/a.txt', size: null }]);
  });

  it('parses markdown style [文件](PATH "FILENAME") format', () => {
    const result = parseFileTokens('[文件](uploads/a.txt "a.txt")');
    expect(result).toEqual([{ fileName: 'a.txt', path: 'uploads/a.txt', size: null }]);
  });

  it('parses multiple file tokens in one message', () => {
    const content = '请查看 [文件:uploads/a.txt]a.txt|1024 和 [文件:uploads/b.png]b.png|5120';
    const result = parseFileTokens(content);
    expect(result).toHaveLength(2);
    expect(result[0].fileName).toBe('a.txt');
    expect(result[1].fileName).toBe('b.png');
  });

  it('preserves text when stripping file tokens', () => {
    const content = '请查看 [文件:uploads/a.txt]a.txt|1024 这个文件';
    const stripped = stripFileTokens(content);
    expect(stripped).not.toContain('[文件');
    expect(stripped).toContain('请查看');
    expect(stripped).toContain('这个文件');
  });

  it('returns original content when no file tokens present', () => {
    expect(stripFileTokens('hello world')).toBe('hello world');
  });

  it('handles file names with multiple dots', () => {
    const result = parseFileTokens('[文件:uploads/my.file.name.txt]my.file.name.txt|100');
    expect(result[0].fileName).toBe('my.file.name.txt');
  });
});
