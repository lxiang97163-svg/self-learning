# -*- coding: utf-8 -*-
"""离线自检：双题材锚证据表（不调用行情 API）。"""
from __future__ import annotations

import sys

import pandas as pd

from generate_review_from_tushare import _build_overlap_anchor_section


def main() -> int:
    top = [("", "概念A", 10), ("", "概念B", 8)]
    theme_map = {
        "概念A": ["002975.SZ", "000586.SZ"],
        "概念B": ["002975.SZ", "603950.SH"],
    }
    zt_map = {
        "002975.SZ": pd.Series({"ts_code": "002975.SZ", "name": "博杰股份"}),
    }
    md = _build_overlap_anchor_section(
        "2026-04-09", {"002975.SZ"}, top, theme_map, zt_map
    )
    assert "Top5概念交集" in md
    assert "002975.SZ" in md
    assert "双题材锚·次日预案" in md
    print("OK: overlap anchor section smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
