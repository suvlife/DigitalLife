import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ArchivePage from './ArchivePage.vue';

const replace = vi.fn();
const api = vi.hoisted(() => ({ getTeams: vi.fn(), getRuns: vi.fn() }));
vi.mock('../api/client', () => api);
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: {}, query: {} }),
  useRouter: () => ({ replace }),
}));

const teams = [
  { id: 1, name: '经世院', i18n: {}, enabled: true, config: {} },
  { id: 2, name: '格物院', i18n: {}, enabled: true, config: {} },
];
function run(id: number, phase = 'completed') {
  return { id: String(id), teamId: 1, title: `卷宗 ${id}`, question: `问题摘要 ${id}`, phase, progress: phase === 'completed' ? 100 : 45, publication: { status: id % 2 ? 'published' : 'idle' }, createdAt: '2026-07-11T08:00:00Z' };
}

describe('ArchivePage', () => {
  beforeEach(() => {
    replace.mockReset();
    api.getTeams.mockResolvedValue(teams);
    api.getRuns.mockResolvedValue([run(1), run(2, 'discussing')]);
  });

  it('renders historical run fields and filters by status', async () => {
    const wrapper = mount(ArchivePage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } });
    await flushPromises();
    expect(api.getRuns).toHaveBeenCalledWith(1, 200);
    expect(wrapper.text()).toContain('卷宗 1');
    expect(wrapper.text()).toContain('问题摘要 1');
    expect(wrapper.text()).toContain('博客 · 已发布');
    expect(wrapper.text()).toContain('100%');
    await wrapper.get('[aria-label="状态筛选"]').setValue('discussing');
    expect(wrapper.text()).not.toContain('卷宗 1');
    expect(wrapper.text()).toContain('卷宗 2');
  });

  it('is pagination-aware and reloads when team changes', async () => {
    api.getRuns.mockResolvedValueOnce(Array.from({ length: 12 }, (_, index) => run(index + 1))).mockResolvedValueOnce([run(21)]);
    const wrapper = mount(ArchivePage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } });
    await flushPromises();
    expect(wrapper.text()).toContain('第 1 / 2 页');
    expect(wrapper.findAll('.archive-card')).toHaveLength(10);
    await wrapper.findAll('nav button')[1].trigger('click');
    expect(wrapper.findAll('.archive-card')).toHaveLength(2);
    await wrapper.get('[aria-label="团队筛选"]').setValue('2');
    await flushPromises();
    expect(replace).toHaveBeenCalledWith({ query: { team: '2' } });
    expect(api.getRuns).toHaveBeenLastCalledWith(2, 200);
    expect(wrapper.text()).toContain('卷宗 21');
  });
});
