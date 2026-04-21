# -*- coding: utf-8 -*-
"""Central paths for daily-review: structured outputs under <workspace>/outputs/."""
from pathlib import Path

_WORKSPACE = Path(__file__).resolve().parent.parent
OUTPUTS = _WORKSPACE / "outputs"
# 按日/按任务的 md、json、pdf
REVIEW_DIR = OUTPUTS / "review"
# 经验库、情绪日历、方法论 txt、板块映射等长期知识资产
KNOWLEDGE_DIR = OUTPUTS / "knowledge"
# 校准与 API 拉取缓存（含隐藏子目录）
CACHE_DIR = OUTPUTS / "cache"
# 本目录：脚本运行时临时文件（如 _nuxt_expr.js）
PIPELINE_DIR = Path(__file__).resolve().parent
# 监控类脚本日志
LOGS_DIR = OUTPUTS / "logs"

for _d in (REVIEW_DIR, KNOWLEDGE_DIR, CACHE_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
