import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import TeamConfigurationEditor from './TeamConfigurationEditor.vue';
const members = [{ id: 7, name: '诸葛', i18n: {}, employee_number: 1, role_template_id: 3, model: 'gpt-x', driver: 'native' }];
const roles = [{ id: 3, name: '谋士', i18n: {}, soul: '善谋', type: 'USER' }];
const rooms = [{ id: 9, name: '中军帐', i18n: {}, type: 'group', initial_topic: '年度规划', max_rounds: 8, agent_ids: [-1, 7], agents: ['OPERATOR', '诸葛'], biz_id: null, tags: [] }];
const llms = [{ name: '主模型', base_url: 'https://llm.test', api_key: '', type: 'openai-compatible' as const, model: 'gpt-x', enable: true, extra_headers: {} }];
function mountEditor() { return mount(TeamConfigurationEditor, { props: { members, roles, rooms, llmServices: llms, teamLlm: '主模型', deptTree: null } }); }
describe('TeamConfigurationEditor', () => {
  it('edits members and emits the full roster', async () => { const wrapper=mountEditor(); await wrapper.get('input[aria-label="成员姓名"]').setValue('孔明'); await wrapper.findAll('button').find(b=>b.text()==='新增成员')!.trigger('click'); await wrapper.findAll('input[aria-label="成员姓名"]')[1].setValue('庞统'); await wrapper.findAll('button').find(b=>b.text()==='保存成员名册')!.trigger('click'); expect(wrapper.emitted('saveMembers')?.[0][0]).toMatchObject([{id:7,name:'孔明'},{id:0,name:'庞统',role_template_id:3,driver:'native'}]); });
  it('creates a room with operator, topic, and rounds', async () => { const wrapper=mountEditor(); await wrapper.findAll('button').find(b=>b.text()==='新增研究室')!.trigger('click'); await wrapper.findAll('input[aria-label="研究室名称"]')[1].setValue('西厢研究室'); const editor=wrapper.findAll('.room-editor')[1]; await editor.find('input[type="checkbox"]').setValue(true); await editor.findAll('button').find(b=>b.text()==='保存研究室')!.trigger('click'); expect(wrapper.emitted('saveRoom')?.[0][0]).toMatchObject({id:0,name:'西厢研究室',max_rounds:10,agent_ids:[7,-1]}); });
  it('builds and emits an organization root', async () => { const wrapper=mountEditor(); await wrapper.findAll('button').find(b=>b.text()==='建立组织树')!.trigger('click'); await wrapper.get('.dept-node-editor input[type="checkbox"]').setValue(true); await wrapper.get('.dept-node-editor select').setValue('7'); await wrapper.findAll('button').find(b=>b.text()==='保存组织树')!.trigger('click'); expect(wrapper.emitted('saveDept')?.[0][0]).toMatchObject({name:'总院',manager_id:7,agent_ids:[7],children:[]}); });
});
