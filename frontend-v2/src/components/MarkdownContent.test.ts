import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import MarkdownContent from './MarkdownContent.vue';

describe('MarkdownContent file tokens', () => {
  it('renders uploaded-file downloads with the owning team id', () => {
    const wrapper = mount(MarkdownContent, { props: { content: '[文件:uploads/input.docx]原始材料|2048', teamId: 9 } });
    const link = wrapper.get('a.file-token');
    expect(link.attributes('href')).toBe('/files/download.json?team_id=9&path=uploads%2Finput.docx');
    expect(link.text()).toContain('原始材料');
  });
});
