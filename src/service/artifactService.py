"""Office 文档读取与生成服务。所有路径都限制在当前团队工作目录。"""
from __future__ import annotations
import csv, json, os, re
from pathlib import Path
from dal.db import gtTeamManager
from service.roomService import ToolCallContext
from util import configUtil, fileUtil


def _safe_name(value:str)->str:
    return re.sub(r'[^\w\u4e00-\u9fff.-]+','_',value.strip())[:80] or '数字人生文档'

async def _team_workdir(context:ToolCallContext)->Path:
    team=await gtTeamManager.get_team_by_id(context.team_id)
    if team is None: raise ValueError('当前团队不存在')
    root=configUtil.get_app_config().setting.workspace_root
    if not root: raise ValueError('团队工作目录尚未配置')
    workdir=Path((team.config or {}).get('working_directory') or os.path.join(root,team.name)).resolve()
    workdir.mkdir(parents=True,exist_ok=True)
    return workdir

def _resolve(workdir:Path,relative_path:str)->Path:
    path=(workdir/relative_path).resolve();fileUtil.assert_path_within_sandbox(str(path),str(workdir));return path

async def extract_office_file(path:str,_context:ToolCallContext=None)->dict:
    """读取已上传的 Word、Excel、PPT、Markdown 或文本文件并返回可供分析的正文。

    Args:
        path: 团队工作目录中的相对路径，如 uploads/20260711_report.docx。
    """
    if _context is None:return {'success':False,'message':'缺少团队上下文'}
    workdir=await _team_workdir(_context);source=_resolve(workdir,path)
    if not source.is_file():return {'success':False,'message':f'未找到文件: {path}'}
    ext=source.suffix.lower();parts=[]
    if ext in {'.md','.markdown','.txt','.json','.csv'}:
        text=source.read_text(encoding='utf-8',errors='replace')
    elif ext=='.docx':
        from docx import Document
        doc=Document(source);parts.extend(p.text for p in doc.paragraphs if p.text.strip())
        for table in doc.tables:
            parts.extend(' | '.join(cell.text for cell in row.cells) for row in table.rows)
        text='\n'.join(parts)
    elif ext in {'.xlsx','.xlsm'}:
        from openpyxl import load_workbook
        book=load_workbook(source,data_only=False,read_only=True)
        for sheet in book.worksheets:
            parts.append(f'## 工作表：{sheet.title}')
            for row in sheet.iter_rows(values_only=True):parts.append(' | '.join('' if v is None else str(v) for v in row))
        text='\n'.join(parts)
    elif ext=='.pptx':
        from pptx import Presentation
        deck=Presentation(source)
        for index,slide in enumerate(deck.slides,1):
            parts.append(f'## 第 {index} 页')
            parts.extend(shape.text for shape in slide.shapes if hasattr(shape,'text') and shape.text.strip())
        text='\n'.join(parts)
    else:return {'success':False,'message':f'当前不能直接解析 {ext}；请先转换为 docx/xlsx/pptx/md'}
    limit=120000;return {'success':True,'path':path,'characters':len(text),'truncated':len(text)>limit,'content':text[:limit]}

async def generate_office_file(format:str,title:str,content:str,filename:str='',_context:ToolCallContext=None)->dict:
    """生成 Word、Excel、PPT 或 Markdown 文件并保存到 outputs 目录。

    Args:
        format: docx、xlsx、pptx 或 md。
        title: 文档标题。
        content: Markdown 风格正文；生成 Excel 时每行可用竖线分隔列，生成 PPT 时用二级标题分隔页面。
        filename: 可选文件名，不含目录。
    """
    if _context is None:return {'success':False,'message':'缺少团队上下文'}
    fmt=format.lower().lstrip('.');allowed={'docx','xlsx','pptx','md'}
    if fmt not in allowed:return {'success':False,'message':'仅支持 docx、xlsx、pptx、md'}
    workdir=await _team_workdir(_context);out=workdir/'outputs';out.mkdir(parents=True,exist_ok=True)
    name=_safe_name(Path(filename).stem if filename else title)+'.'+fmt;target=_resolve(workdir,f'outputs/{name}')
    lines=[line.rstrip() for line in content.splitlines()]
    if fmt=='md':target.write_text(f'# {title}\n\n{content.strip()}\n',encoding='utf-8')
    elif fmt=='docx':
        from docx import Document
        from docx.shared import Pt
        doc=Document();doc.add_heading(title,0)
        for line in lines:
            stripped=line.strip()
            if not stripped:doc.add_paragraph();continue
            level=len(stripped)-len(stripped.lstrip('#'))
            if level:doc.add_heading(stripped[level:].strip(),level=min(3,level))
            elif stripped.startswith(('- ','* ')):doc.add_paragraph(stripped[2:],style='List Bullet')
            else:doc.add_paragraph(stripped)
        for style in doc.styles:
            if hasattr(style,'font'):style.font.name='LXGW WenKai';style.font.size=style.font.size or Pt(11)
        doc.save(target)
    elif fmt=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment
        wb=Workbook();ws=wb.active;ws.title=_safe_name(title)[:31]
        rows=[]
        for line in lines:
            if not line.strip():continue
            cells=[x.strip() for x in line.strip().strip('|').split('|')] if '|' in line else [line.strip()]
            if cells and all(set(x)<=set('-: ') for x in cells):continue
            rows.append(cells)
        for row in rows:ws.append(row)
        if rows:
            for cell in ws[1]:cell.font=Font(name='LXGW WenKai',bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='365B47');cell.alignment=Alignment(horizontal='center')
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
            for column in ws.columns:
                letter=column[0].column_letter;ws.column_dimensions[letter].width=min(42,max(10,max(len(str(c.value or '')) for c in column)+2))
        wb.save(target)
    else:
        from pptx import Presentation
        from pptx.util import Inches,Pt
        deck=Presentation();deck.slide_width=Inches(13.333);deck.slide_height=Inches(7.5)
        cover=deck.slides.add_slide(deck.slide_layouts[0]);cover.shapes.title.text=title;cover.placeholders[1].text='数字人生 · 智能协作生成'
        sections=[];current=('内容提要',[])
        for line in lines:
            if line.startswith('## '):sections.append(current);current=(line[3:].strip(),[])
            elif line.strip():current[1].append(line.lstrip('#- * ').strip())
        sections.append(current)
        for heading,items in sections:
            if not items and heading=='内容提要':continue
            slide=deck.slides.add_slide(deck.slide_layouts[1]);slide.shapes.title.text=heading;frame=slide.placeholders[1].text_frame;frame.clear()
            for i,item in enumerate(items[:8]):p=frame.paragraphs[0] if i==0 else frame.add_paragraph();p.text=item;p.font.size=Pt(22)
        deck.save(target)
    return {'success':True,'format':fmt,'filename':name,'path':f'outputs/{name}','message':f'已生成 {name}'}
