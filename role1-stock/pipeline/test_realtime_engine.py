# -*- coding: utf-8 -*-
"""realtime_engine 自检：不依赖 pytest，直接 python test_realtime_engine.py"""
import os
import sys
import tempfile

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PIPELINE_DIR)

from _paths import REVIEW_DIR

BASE = str(REVIEW_DIR)

from realtime_engine import (  # noqa: E402
    parse_speedcard_structure,
    parse_card,
    pack_strong_signals,
    run_once,
    _CARD_FALLBACK,
)

FIXTURE = os.path.join(BASE, "速查_2026-03-31.md")


def test_parse_structure_from_fixture():
    if not os.path.exists(FIXTURE):
        print(f"SKIP: 无 {FIXTURE}")
        return
    with open(FIXTURE, "r", encoding="utf-8") as f:
        content = f.read()
    s = parse_speedcard_structure(content)
    assert len(s["p1_chain"]) >= 1, "第一优先顺位应有数据"
    assert len(s["p2_chain"]) >= 1, "第二优先顺位应有数据"
    assert len(s["watch_packages"]) >= 1, "盘中观察包至少一包"
    assert 3000 < s["key_support"] < 5000, "关键支撑应在合理区间"
    wp0 = s["watch_packages"][0]
    assert len(wp0["stocks"]) == 5, "每包应 5 只"
    print("OK test_parse_structure_from_fixture")


def test_pack_strong_signals():
    pack = {
        "stocks": [
            {"ts_code": "000001.SZ", "name": "A", "rank": 1},
            {"ts_code": "000002.SZ", "name": "B", "rank": 2},
        ]
    }
    code_to_row = {
        "000001": ("A", "000001", 11.0, 10.0, 1e9),
        "000002": ("B", "000002", 6.0, 5.5, 1e8),
    }
    c2, c3, _ = pack_strong_signals(pack, code_to_row)
    assert c2 is True
    assert c3 is True


def test_parse_card_override_missing():
    sm, sec, path, st = parse_card(override_path=os.path.join(BASE, "__no_such_file__.md"))
    assert sm == {}
    assert st == {}


def test_run_once_smoke():
    if not os.path.exists(FIXTURE):
        print("SKIP test_run_once_smoke: 无 fixture")
        return
    log = os.path.join(tempfile.gettempdir(), "rt_test_log.txt")
    txt = run_once(log, use_playwright=False, card_path=FIXTURE)
    assert "综合快照" in txt
    assert "盘中观察" in txt or "第一优先" in txt
    assert os.path.isfile(log)
    print("OK test_run_once_smoke ->", log)


def main():
    test_parse_structure_from_fixture()
    test_pack_strong_signals()
    test_parse_card_override_missing()
    test_run_once_smoke()
    fb = os.path.join(BASE, _CARD_FALLBACK)
    sm, _, path, st = parse_card()
    if sm:
        assert "watch_packages" in str(st) or st.get("watch_packages") is not None
        print("OK parse_card default path:", path)
    else:
        print("WARN: 无当日速查且无回退，parse_card 为空；可用 --card 指定", FIXTURE)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
