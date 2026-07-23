"""Token 用量统计服务。

基于 agent_activities 表中 LLM_INFER / COMPACT 活动的 metadata 字段，
提供按 agent / model / day 等维度的聚合统计。

聚合在 SQL 层完成（json_extract + GROUP BY），避免同一窗口全表扫描多遍
并将全部行搬运到 Python；token 提取语义与旧 Python 聚合严格对齐：
- `a or b or 0` 的 falsy 语义（0/None 视为缺失）通过 NULLIF(..., 0) 复刻；
- total 缺失时回退为已解析的 prompt + completion；
- model 仅接受 JSON 字符串，空串/非字符串一律归为 "unknown"；
- 仅统计 total > 0 的行。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from peewee import Case, fn

from constants import AgentActivityStatus, AgentActivityType
from model.dbModel.gtAgentActivity import GtAgentActivity

logger = logging.getLogger(__name__)

_META = GtAgentActivity.metadata


# ─── SQL 表达式（token 提取语义见模块 docstring）────────────────────────────

def _prompt_expr() -> Any:
    return fn.COALESCE(
        fn.NULLIF(fn.json_extract(_META, "$.final_prompt_tokens"), 0),
        fn.NULLIF(fn.json_extract(_META, "$.prompt_tokens"), 0),
        0,
    )


def _completion_expr() -> Any:
    return fn.COALESCE(
        fn.NULLIF(fn.json_extract(_META, "$.final_completion_tokens"), 0),
        fn.NULLIF(fn.json_extract(_META, "$.completion_tokens"), 0),
        0,
    )


def _total_expr() -> Any:
    return fn.COALESCE(
        fn.NULLIF(fn.json_extract(_META, "$.final_total_tokens"), 0),
        fn.NULLIF(fn.json_extract(_META, "$.total_tokens"), 0),
        _prompt_expr() + _completion_expr(),
    )


def _model_expr() -> Any:
    return fn.COALESCE(
        fn.NULLIF(
            Case(
                None,
                ((fn.json_type(_META, "$.model") == "text", fn.json_extract(_META, "$.model")),),
                None,
            ),
            "",
        ),
        "unknown",
    )


def _overflow_expr() -> Any:
    # JSON true 经 json_extract 取出为 1；与旧 Python 的 truthy 判断对齐
    return Case(None, ((fn.json_extract(_META, "$.overflow_retry") == True, 1),), 0)  # noqa: E712


def _base_conditions(
    team_id: int | None,
    agent_ids: list[int] | None,
    since: datetime | None,
    until: datetime | None,
) -> list[Any]:
    """构建针对 LLM_INFER 活动的基础过滤条件。"""
    conditions: list[Any] = [
        GtAgentActivity.activity_type == AgentActivityType.LLM_INFER,
        GtAgentActivity.status != AgentActivityStatus.CANCELLED,
    ]
    if team_id is not None:
        conditions.append(GtAgentActivity.team_id == team_id)
    if agent_ids:
        conditions.append(GtAgentActivity.agent_id.in_(agent_ids))
    if since is not None:
        conditions.append(GtAgentActivity.started_at >= since)
    if until is not None:
        conditions.append(GtAgentActivity.started_at <= until)
    return conditions


async def get_usage_summary_by_agent(
    team_id: int | None = None,
    agent_ids: list[int] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """按 Agent 聚合 token 用量。"""
    total_expr = _total_expr()
    rows = await (
        GtAgentActivity.select(
            GtAgentActivity.agent_id,
            fn.COUNT(GtAgentActivity.id).alias("request_count"),
            fn.COALESCE(fn.SUM(_prompt_expr()), 0).alias("prompt_tokens"),
            fn.COALESCE(fn.SUM(_completion_expr()), 0).alias("completion_tokens"),
            fn.COALESCE(fn.SUM(total_expr), 0).alias("total_tokens"),
        )
        .where(*_base_conditions(team_id, agent_ids, since, until), total_expr > 0)
        .group_by(GtAgentActivity.agent_id)
        .order_by(fn.SUM(total_expr).desc(), GtAgentActivity.agent_id)
        .dicts()
        .aio_execute()
    )
    return [dict(row) for row in rows]


async def get_usage_summary_by_day(
    since: datetime,
    until: datetime,
    team_id: int | None = None,
    agent_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """按天聚合 token 用量，返回时间序列。"""
    total_expr = _total_expr()
    day_expr = fn.strftime("%Y-%m-%d", GtAgentActivity.started_at)
    rows = await (
        GtAgentActivity.select(
            day_expr.alias("date"),
            fn.COUNT(GtAgentActivity.id).alias("request_count"),
            fn.COALESCE(fn.SUM(_prompt_expr()), 0).alias("prompt_tokens"),
            fn.COALESCE(fn.SUM(_completion_expr()), 0).alias("completion_tokens"),
            fn.COALESCE(fn.SUM(total_expr), 0).alias("total_tokens"),
        )
        .where(*_base_conditions(team_id, agent_ids, since, until), total_expr > 0)
        .group_by(day_expr)
        .order_by(day_expr)
        .dicts()
        .aio_execute()
    )
    agg = {row["date"]: dict(row) for row in rows}

    # 填充无数据的日期为 0
    result = []
    cursor = since.date()
    end = until.date()
    while cursor <= end:
        day_str = cursor.strftime("%Y-%m-%d")
        result.append(agg.get(day_str, {
            "date": day_str,
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }))
        cursor += timedelta(days=1)

    return result


async def get_usage_summary_by_model(
    team_id: int | None = None,
    agent_ids: list[int] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """按模型聚合 token 用量（metadata.model）。"""
    total_expr = _total_expr()
    model_expr = _model_expr()
    rows = await (
        GtAgentActivity.select(
            model_expr.alias("model"),
            fn.COUNT(GtAgentActivity.id).alias("request_count"),
            fn.COALESCE(fn.SUM(_prompt_expr()), 0).alias("prompt_tokens"),
            fn.COALESCE(fn.SUM(_completion_expr()), 0).alias("completion_tokens"),
            fn.COALESCE(fn.SUM(total_expr), 0).alias("total_tokens"),
        )
        .where(*_base_conditions(team_id, agent_ids, since, until), total_expr > 0)
        .group_by(model_expr)
        .order_by(fn.SUM(total_expr).desc(), model_expr)
        .dicts()
        .aio_execute()
    )
    return [dict(row) for row in rows]


async def get_usage_total(
    team_id: int | None = None,
    agent_ids: list[int] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """汇总 token 总量、请求次数、compact 触发次数、overflow retry 次数。"""
    total_expr = _total_expr()
    rows = await (
        GtAgentActivity.select(
            fn.COUNT(GtAgentActivity.id).alias("request_count"),
            fn.COALESCE(fn.SUM(_prompt_expr()), 0).alias("prompt_tokens"),
            fn.COALESCE(fn.SUM(_completion_expr()), 0).alias("completion_tokens"),
            fn.COALESCE(fn.SUM(total_expr), 0).alias("total_tokens"),
            fn.COALESCE(fn.SUM(_overflow_expr()), 0).alias("overflow_retry_count"),
        )
        .where(*_base_conditions(team_id, agent_ids, since, until), total_expr > 0)
        .dicts()
        .aio_execute()
    )
    totals = dict(rows[0]) if rows else {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "overflow_retry_count": 0,
    }

    compact_query = GtAgentActivity.select().where(
        GtAgentActivity.activity_type == AgentActivityType.COMPACT,
        GtAgentActivity.status != AgentActivityStatus.CANCELLED,
    )
    if team_id is not None:
        compact_query = compact_query.where(GtAgentActivity.team_id == team_id)
    if agent_ids:
        compact_query = compact_query.where(GtAgentActivity.agent_id.in_(agent_ids))
    if since is not None:
        compact_query = compact_query.where(GtAgentActivity.started_at >= since)
    if until is not None:
        compact_query = compact_query.where(GtAgentActivity.started_at <= until)
    compact_count = await compact_query.aio_count()

    return {
        "request_count": totals["request_count"],
        "prompt_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "total_tokens": totals["total_tokens"],
        "compact_count": compact_count,
        "overflow_retry_count": totals["overflow_retry_count"],
    }


async def get_usage_summary(
    team_id: int | None = None,
    agent_ids: list[int] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """返回完整的 token 用量统计面板数据。"""
    return {
        "total": await get_usage_total(team_id, agent_ids, since, until),
        "by_agent": await get_usage_summary_by_agent(team_id, agent_ids, since, until),
        "by_model": await get_usage_summary_by_model(team_id, agent_ids, since, until),
        "by_day": await get_usage_summary_by_day(
            since or (datetime.now() - timedelta(days=6)),
            until or datetime.now(),
            team_id,
            agent_ids,
        ),
    }
