"""usageService SQL 聚合对拍测试：与旧 Python 聚合语义逐字段一致。

覆盖 metadata 各种形态：final_* 字段、旧版 prompt_tokens 字段、0 值回退、
total 缺失时 prompt+completion 兜底、非字符串/空 model、overflow_retry、
CANCELLED 排除、total<=0 排除、by_day 零填充。
"""
import os
import sys
from datetime import datetime, timedelta

import service.ormService as ormService
from constants import AgentActivityStatus, AgentActivityType
from model.dbModel.gtAgentActivity import GtAgentActivity
from service import usageService
from tests.base import ServiceTestCase

if os.name == "posix" and sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")


# ─── 旧 Python 聚合逻辑（对拍基准，保持与修复前实现逐行一致）─────────────────

def _old_extract_tokens(metadata: dict | None) -> tuple[int, int, int]:
    if metadata is None:
        return 0, 0, 0
    prompt = metadata.get("final_prompt_tokens") or metadata.get("prompt_tokens") or 0
    completion = metadata.get("final_completion_tokens") or metadata.get("completion_tokens") or 0
    total = metadata.get("final_total_tokens") or metadata.get("total_tokens") or (prompt + completion)
    return int(prompt), int(completion), int(total)


def _old_filter(rows, team_id, agent_ids, since, until):
    result = []
    for row in rows:
        if row.activity_type != AgentActivityType.LLM_INFER:
            continue
        if row.status == AgentActivityStatus.CANCELLED:
            continue
        if team_id is not None and row.team_id != team_id:
            continue
        if agent_ids and row.agent_id not in agent_ids:
            continue
        if since is not None and row.started_at < since:
            continue
        if until is not None and row.started_at > until:
            continue
        result.append(row)
    return result


def _old_by_agent(rows):
    agg = {}
    for row in rows:
        prompt, completion, total = _old_extract_tokens(row.metadata)
        if total <= 0:
            continue
        entry = agg.setdefault(row.agent_id, {
            "agent_id": row.agent_id, "request_count": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })
        entry["request_count"] += 1
        entry["prompt_tokens"] += prompt
        entry["completion_tokens"] += completion
        entry["total_tokens"] += total
    return sorted(agg.values(), key=lambda x: x["total_tokens"], reverse=True)


def _old_by_model(rows):
    agg = {}
    for row in rows:
        prompt, completion, total = _old_extract_tokens(row.metadata)
        if total <= 0:
            continue
        model = (row.metadata or {}).get("model") or "unknown"
        if not isinstance(model, str):
            model = "unknown"
        entry = agg.setdefault(model, {
            "model": model, "request_count": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })
        entry["request_count"] += 1
        entry["prompt_tokens"] += prompt
        entry["completion_tokens"] += completion
        entry["total_tokens"] += total
    return sorted(agg.values(), key=lambda x: x["total_tokens"], reverse=True)


def _old_by_day(rows, since, until):
    agg = {}
    for row in rows:
        prompt, completion, total = _old_extract_tokens(row.metadata)
        if total <= 0:
            continue
        day = row.started_at.strftime("%Y-%m-%d")
        entry = agg.setdefault(day, {
            "date": day, "request_count": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })
        entry["request_count"] += 1
        entry["prompt_tokens"] += prompt
        entry["completion_tokens"] += completion
        entry["total_tokens"] += total
    result = []
    cursor = since.date()
    end = until.date()
    while cursor <= end:
        day_str = cursor.strftime("%Y-%m-%d")
        result.append(agg.get(day_str, {
            "date": day_str, "request_count": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }))
        cursor += timedelta(days=1)
    return result


def _old_total(rows, compact_rows):
    total_prompt = total_completion = total_tokens = request_count = overflow_count = 0
    for row in rows:
        prompt, completion, total = _old_extract_tokens(row.metadata)
        if total <= 0:
            continue
        request_count += 1
        total_prompt += prompt
        total_completion += completion
        total_tokens += total
        if (row.metadata or {}).get("overflow_retry"):
            overflow_count += 1
    return {
        "request_count": request_count,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "compact_count": len(compact_rows),
        "overflow_retry_count": overflow_count,
    }


# ─── 测试数据集 ────────────────────────────────────────────────────────────

_BASE_TIME = datetime(2026, 7, 20, 12, 0, 0)


def _activity(agent_id, team_id, metadata, *, day_offset=0, status=AgentActivityStatus.SUCCEEDED,
              activity_type=AgentActivityType.LLM_INFER):
    return GtAgentActivity(
        agent_id=agent_id, team_id=team_id,
        activity_type=activity_type, status=status,
        title="推理", started_at=_BASE_TIME + timedelta(days=day_offset),
        metadata=metadata,
    )


def _dataset() -> list[GtAgentActivity]:
    return [
        # agent 1 / team 1：final_* 形态
        _activity(1, 1, {"final_prompt_tokens": 100, "final_completion_tokens": 50,
                          "final_total_tokens": 150, "model": "gpt-a"}),
        # agent 1 / team 1：旧版字段形态 + overflow_retry
        _activity(1, 1, {"prompt_tokens": 10, "completion_tokens": 5,
                          "total_tokens": 15, "model": "gpt-a", "overflow_retry": True},
                   day_offset=1),
        # agent 2 / team 1：total 缺失 → prompt+completion 兜底
        _activity(2, 1, {"prompt_tokens": 7, "completion_tokens": 3, "model": "gpt-b"},
                   day_offset=1),
        # agent 2 / team 1：final=0 时回退旧字段（Python `or` 语义）
        _activity(2, 1, {"final_prompt_tokens": 0, "prompt_tokens": 20,
                          "final_completion_tokens": 0, "completion_tokens": 4,
                          "final_total_tokens": 0, "total_tokens": 24, "model": ""},
                   day_offset=2),
        # agent 3 / team 1：非字符串 model → unknown
        _activity(3, 1, {"final_total_tokens": 30, "model": 123}, day_offset=2),
        # agent 3 / team 2：另一个团队
        _activity(3, 2, {"final_total_tokens": 40, "model": "gpt-c"}, day_offset=3),
        # CANCELLED 应排除
        _activity(1, 1, {"final_total_tokens": 999, "model": "gpt-a"},
                   status=AgentActivityStatus.CANCELLED),
        # total<=0 应排除（request_count 也不计）
        _activity(1, 1, {"model": "gpt-a"}),
        _activity(1, 1, {"final_total_tokens": 0, "model": "gpt-a"}),
        # COMPACT 活动：team 1 两条（其中一条 CANCELLED 不计）、team 2 一条
        _activity(1, 1, {}, activity_type=AgentActivityType.COMPACT),
        _activity(2, 1, {}, activity_type=AgentActivityType.COMPACT,
                   status=AgentActivityStatus.CANCELLED),
        _activity(3, 2, {}, activity_type=AgentActivityType.COMPACT, day_offset=1),
    ]


class TestUsageServiceSqlAggregation(ServiceTestCase):
    """SQL 聚合 vs 旧 Python 聚合对拍。"""

    @classmethod
    async def async_setup_class(cls):
        db_path = cls._get_test_db_path()
        await ormService.startup(db_path)

    @classmethod
    async def async_teardown_class(cls):
        await ormService.shutdown()

    async def _reload_dataset(self) -> list[GtAgentActivity]:
        await GtAgentActivity.delete().aio_execute()
        for item in _dataset():
            await item.aio_save()
        return list(await GtAgentActivity.select().aio_execute())

    async def test_by_agent_parity(self):
        rows = await self._reload_dataset()
        for team_id, agent_ids in ((None, None), (1, None), (2, None), (1, [1, 2]), (None, [3])):
            expected = _old_by_agent(_old_filter(rows, team_id, agent_ids, None, None))
            actual = await usageService.get_usage_summary_by_agent(team_id, agent_ids, None, None)
            assert actual == [dict(x) for x in expected], f"team_id={team_id}, agent_ids={agent_ids}"

    async def test_by_model_parity(self):
        rows = await self._reload_dataset()
        for team_id, agent_ids in ((None, None), (1, None), (2, None)):
            expected = _old_by_model(_old_filter(rows, team_id, agent_ids, None, None))
            actual = await usageService.get_usage_summary_by_model(team_id, agent_ids, None, None)
            # model 聚合旧实现按 total desc 排序（稳定序为首次出现序），新实现按 (total desc, model)
            # 对拍按 model 建索引后逐条比对，避免并列时的排序差异干扰
            assert len(actual) == len(expected)
            expected_by_model = {x["model"]: x for x in expected}
            for entry in actual:
                assert entry == expected_by_model[entry["model"]], f"team_id={team_id}"

    async def test_by_day_parity_and_zero_fill(self):
        rows = await self._reload_dataset()
        since = _BASE_TIME - timedelta(days=1)
        until = _BASE_TIME + timedelta(days=5)
        expected = _old_by_day(_old_filter(rows, None, None, since, until), since, until)
        actual = await usageService.get_usage_summary_by_day(since, until)
        assert actual == expected
        # 无数据日期零填充
        empty_day = (_BASE_TIME + timedelta(days=5)).strftime("%Y-%m-%d")
        filled = [x for x in actual if x["date"] == empty_day][0]
        assert filled == {"date": empty_day, "request_count": 0,
                          "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def test_total_parity(self):
        rows = await self._reload_dataset()
        infer_rows = _old_filter(rows, None, None, None, None)
        compact_rows = [r for r in rows
                        if r.activity_type == AgentActivityType.COMPACT
                        and r.status != AgentActivityStatus.CANCELLED]
        expected = _old_total(infer_rows, compact_rows)
        actual = await usageService.get_usage_total()
        assert actual == expected

        # 带过滤条件的对拍
        infer_rows = _old_filter(rows, 1, [1, 2], None, None)
        compact_rows = [r for r in compact_rows if r.team_id == 1 and r.agent_id in (1, 2)]
        expected = _old_total(infer_rows, compact_rows)
        actual = await usageService.get_usage_total(1, [1, 2], None, None)
        assert actual == expected

    async def test_empty_result_shape(self):
        await GtAgentActivity.delete().aio_execute()
        total = await usageService.get_usage_total()
        assert total == {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0,
                         "total_tokens": 0, "compact_count": 0, "overflow_retry_count": 0}
        assert await usageService.get_usage_summary_by_agent() == []
        assert await usageService.get_usage_summary_by_model() == []
