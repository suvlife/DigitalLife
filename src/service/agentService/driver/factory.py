from __future__ import annotations

import logging
from typing import Any, Mapping

import appPaths
from constants import DriverType
from .base import AgentDriverConfig
from .nativeDriver import NativeAgentDriver
from .claudeSdkDriver import ClaudeSdkAgentDriver
from .tspDriver import TspAgentDriver

logger = logging.getLogger(__name__)


def normalize_driver_config(role_template_cfg: Mapping[str, Any] | Any) -> AgentDriverConfig:
    if hasattr(role_template_cfg, "model_dump"):
        role_template_cfg = role_template_cfg.model_dump()

    driver_cfg = role_template_cfg.get("driver")
    driver_type = DriverType.value_of(driver_cfg) or DriverType.NATIVE
    return AgentDriverConfig(driver_type=driver_type, options={})


def build_agent_driver(
    host: Any,
    driver_config: AgentDriverConfig,
) -> NativeAgentDriver | ClaudeSdkAgentDriver | TspAgentDriver:
    driver_type = driver_config.driver_type
    if isinstance(driver_type, str):
        driver_type = DriverType.value_of(driver_type) or DriverType.NATIVE
        driver_config.driver_type = driver_type

    if driver_type == DriverType.NATIVE:
        return NativeAgentDriver(host, driver_config)
    if driver_type == DriverType.CLAUDE_SDK:
        return ClaudeSdkAgentDriver(host, driver_config)
    if driver_type == DriverType.TSP:
        # A custom command may provide GTSP outside assets/. Otherwise avoid a
        # fatal constructor error and degrade to native when configured.
        custom_command = driver_config.options.get("command")
        if not custom_command:
            diagnostic = appPaths.gtsp_diagnostic()
            if not diagnostic.get("available"):
                fallback_enabled = True
                try:
                    from util import configUtil
                    fallback = configUtil.get_app_config().setting.driver_fallback
                    fallback_enabled = bool(fallback.enabled and fallback.tsp_to_native)
                except Exception:
                    pass
                message = (
                    f"GTSP unavailable for agent_id={getattr(getattr(host, 'gt_agent', None), 'id', None)}; "
                    f"expected={diagnostic.get('path') or diagnostic.get('error')}"
                )
                if fallback_enabled:
                    logger.warning("%s; falling back to native driver", message)
                    fallback_config = AgentDriverConfig(
                        driver_type=DriverType.NATIVE,
                        options={**driver_config.options, "degraded_from": "tsp"},
                    )
                    return NativeAgentDriver(host, fallback_config)
                raise RuntimeError(message + "; enable driver_fallback.tsp_to_native or install GTSP")
        return TspAgentDriver(host, driver_config)
    raise ValueError(f"未知 agent driver 类型: {driver_type}")
