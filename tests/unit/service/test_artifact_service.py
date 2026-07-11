from pathlib import Path
import pytest
from service import artifactService
from service.roomService import ToolCallContext

@pytest.mark.asyncio
async def test_generate_and_extract_office_formats(tmp_path, monkeypatch):
    async def fake_workdir(_context): return tmp_path
    monkeypatch.setattr(artifactService, '_team_workdir', fake_workdir)
    context=ToolCallContext(agent_id=1,team_id=1)
    content='## 第一部分\n- 要点一\n- 要点二\n\n|项目|数值|\n|---|---|\n|甲|10|'
    for fmt in ('md','docx','xlsx','pptx'):
        result=await artifactService.generate_office_file(fmt,'能力测试',content,f'ability-test.{fmt}',context)
        assert result['success'] is True
        assert (tmp_path/result['path']).is_file()
        extracted=await artifactService.extract_office_file(result['path'],context)
        assert extracted['success'] is True
        assert extracted['characters'] > 0
