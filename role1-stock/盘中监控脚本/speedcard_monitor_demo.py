# -*- coding: utf-8 -*-
"""
速查早盘监控 · 演示模式
模拟 9:15～9:50 每分钟执行一次，展示完整窗口的 36 条输出
用法: python3 speedcard_monitor_demo.py
"""
import sys
import os
import time

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE_DIR = os.path.normpath(os.path.join(_SELF_DIR, "..", "pipeline"))
sys.path.insert(0, _PIPELINE_DIR)
sys.path.insert(0, _SELF_DIR)

from speedcard_monitor import build_parsed_card, run_tick, append_log
from _paths import LOGS_DIR

def demo_mode():
    """演示模式：9:15～9:50 每分钟运行一次"""
    pc = build_parsed_card(None)
    if not pc:
        print("未找到速查文件", file=sys.stderr)
        sys.exit(1)

    date_str = time.strftime("%Y-%m-%d")
    print(f"[\033[92m演示模式\033[0m] 从速查 {pc.path} 生成 9:15～9:50 的 36 条输出")
    print(f"日期: {date_str}\n")
    print("=" * 120)

    lines = []
    for minute in range(15, 51):
        hm = 900 + minute  # 9:15 → 915, ..., 9:50 → 950
        try:
            line = run_tick(pc, hm)
            lines.append(line)
            print(f"[\033[94m{hm//100:02d}:{hm%100:02d}\033[0m] {line}")
            time.sleep(0.5)  # 简短延迟，让输出可读
        except Exception as e:
            err = f"[{hm//100:02d}:{hm%100:02d}] 异常: {e}"
            print(f"[\033[91m错误\033[0m] {err}")
            lines.append(err)

    print("=" * 120)
    print(f"\n\033[92m总计 {len(lines)} 条输出\033[0m")

    # 追加到日志
    print(f"\n已追加到: {LOGS_DIR}/speedcard_monitor_demo_{date_str}.log")
    demo_log_path = os.path.join(LOGS_DIR, f"speedcard_monitor_demo_{date_str}.log")
    os.makedirs(os.path.dirname(os.path.abspath(demo_log_path)), exist_ok=True)
    with open(demo_log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    demo_mode()
