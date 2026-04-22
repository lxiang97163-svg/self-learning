"""
竞价策略采集器 — 每日 9:27 运行，捕获三个重构策略的输出写入
dashboard/data/strategy_results.json，供看板「策略报告」Tab 展示。

用法:
    python dashboard/collect_strategy.py
    python dashboard/collect_strategy.py --dry-run
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
STRATEGIES_DIR = DASHBOARD_DIR.parent / "refactored" / "strategies"
DATA_DIR = DASHBOARD_DIR / "data"
OUT_FILE = DATA_DIR / "strategy_results.json"

STRATEGIES = [
    ("jingjia_31_duanban",    "竞价三一·断板弱转强"),
    ("tidui_baoliang_yihong", "一红+爆量"),
    ("sector_scan_9431",      "9431板块扫描"),
    ("danhe_daidui",          "单核带队"),
    ("tidui_fupan",           "梯队复盘"),
]


def _run_one(name: str, label: str) -> dict:
    script = STRATEGIES_DIR / f"{name}.py"
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--no-push"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        elapsed = round(time.monotonic() - t0, 1)
        output = result.stdout or ""
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        return {
            "name": name,
            "label": label,
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "output": output.strip(),
            "elapsed_s": elapsed,
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "label": label,
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "success": False,
            "returncode": -1,
            "output": "[超时：超过 300 秒]",
            "elapsed_s": round(time.monotonic() - t0, 1),
        }
    except Exception as exc:
        return {
            "name": name,
            "label": label,
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "success": False,
            "returncode": -2,
            "output": f"[启动失败] {exc}",
            "elapsed_s": round(time.monotonic() - t0, 1),
        }


def main(dry_run: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for name, label in STRATEGIES:
        if dry_run:
            print(f"[dry-run] 跳过 {label}")
            results.append({
                "name": name, "label": label,
                "run_at": datetime.now().isoformat(timespec="seconds"),
                "success": True, "returncode": 0,
                "output": "[dry-run]", "elapsed_s": 0.0,
            })
        else:
            print(f"运行 {label} ...", flush=True)
            r = _run_one(name, label)
            icon = "OK" if r["success"] else "FAIL"
            print(f"  -> [{icon}] exit={r['returncode']} {r['elapsed_s']}s")
            results.append(r)

    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": datetime.now().strftime("%Y-%m-%d"),
        "strategies": results,
    }
    tmp = OUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT_FILE)
    print(f"写入完成 → {OUT_FILE}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
