# -*- coding: utf-8 -*-
"""
9:28 一进二选股 → PushPlus 推送
用法: python 928_push.py [--date YYYYMMDD]
"""
from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from datetime import datetime

import requests

import importlib.util, os

PUSHPLUS_TOKEN = "66c0490b50c34e74b5cc000232b1d23c"
PUSHPLUS_URL   = "http://www.pushplus.plus/send"
DIR = os.path.dirname(os.path.abspath(__file__))


def _load_cursor():
    spec = importlib.util.spec_from_file_location(
        "cursor_mod", os.path.join(DIR, "928选股_cursor.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_and_capture(date: str) -> str:
    mod = _load_cursor()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.run(date)
    return buf.getvalue()


def format_for_push(raw: str, date: str) -> tuple[str, str]:
    """返回 (title, content)。"""
    lines = [l for l in raw.splitlines() if l.strip()]

    title = f"一进二选股 {date[:4]}-{date[4:6]}-{date[6:]}"

    if "无符合" in raw or not any(".SH" in l or ".SZ" in l for l in lines):
        return title, f"【{date}】今日无符合条件的标的。"

    # 找首选行
    top_line = next((l for l in lines if "今日应选" in l), "")
    top_name = top_line.replace("今日应选：", "").strip() if top_line else "—"

    # 找命中行（含代码的行）
    hit_lines = [l.strip() for l in lines if ".SH" in l or ".SZ" in l]

    content_parts = [
        f"📅 {date[:4]}-{date[4:6]}-{date[6:]}",
        f"🏆 首选：{top_name}",
        "",
        "全部命中（按原型距排序）：",
    ]
    for i, hl in enumerate(hit_lines, 1):
        content_parts.append(f"  {i}. {hl}")

    # 追加参数行
    param_line = next((l.strip() for l in lines if "参数:" in l), "")
    if param_line:
        content_parts += ["", f"参数: {param_line.replace('参数:', '').strip()}"]

    return title, "\n".join(content_parts)


def _print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("gbk", errors="replace").decode("gbk"))


def push(title: str, content: str) -> None:
    try:
        resp = requests.post(
            PUSHPLUS_URL,
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "txt",
                "channel": "wechat",
            },
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("code") == 200:
            _print("[OK] 已推送到微信")
        else:
            _print(f"[ERR] 推送失败: {resp.status_code} {resp.text[:120]}")
    except requests.RequestException as e:
        _print(f"[ERR] 推送异常: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or datetime.now().strftime("%Y%m%d")

    print(f"[928_push] 开始选股 {date}")
    raw = run_and_capture(date)
    print(raw)

    title, content = format_for_push(raw, date)
    _print(f"\n[推送内容]\n{content}\n")
    push(title, content)


if __name__ == "__main__":
    main()
