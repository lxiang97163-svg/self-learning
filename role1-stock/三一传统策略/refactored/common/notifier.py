# -*- coding: utf-8 -*-
"""Notification helpers (PushPlus) and CLI plumbing.

No token strings should appear anywhere else in the refactored code.
All scripts consume :class:`NotifyOptions` produced by :func:`parse_notify_args`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional

import requests


PUSHPLUS_URL = "http://www.pushplus.plus/send"


@dataclass(frozen=True)
class NotifyOptions:
    no_push: bool = False
    output_file: Optional[str] = None

    @property
    def should_push(self) -> bool:
        return not self.no_push and self.output_file is None


def parse_notify_args(
    argv: Optional[list] = None, *, extra_args=None
) -> NotifyOptions:
    """Parse ``--no-push`` / ``--output-file`` uniformly for every strategy."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--output-file", type=str, default=None)
    if extra_args:
        for args, kwargs in extra_args:
            parser.add_argument(*args, **kwargs)
    args, _unknown = parser.parse_known_args(argv)
    return NotifyOptions(
        no_push=args.no_push,
        output_file=args.output_file,
    )


def _safe_print(content: str) -> None:
    try:
        sys.stdout.buffer.write((content + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    except AttributeError:
        print(content)


def dispatch(
    content: str,
    *,
    title: str,
    token: Optional[str],
    options: NotifyOptions,
    verbose: bool = True,
) -> None:
    """Write/print content and optionally push to PushPlus."""

    if options.output_file:
        with open(options.output_file, "w", encoding="utf-8") as fh:
            fh.write(content)
        if verbose:
            print(f"✅ 已写入 {options.output_file}")
        return

    _safe_print(content)

    if options.no_push:
        if verbose:
            print("\n(未推送)")
        return

    if not token:
        if verbose:
            print("\n⚠️ 未配置 pushplus_token，跳过推送。")
        return

    try:
        resp = requests.post(
            PUSHPLUS_URL,
            json={
                "token": token,
                "title": title,
                "content": content,
                "template": "txt",
                "channel": "wechat",
            },
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("code") == 200:
            if verbose:
                print("\n✅ 已推送到微信")
        else:
            if verbose:
                print(f"\n⚠️ 推送失败: status={resp.status_code} body={resp.text[:120]}")
    except requests.RequestException as exc:
        if verbose:
            print(f"\n⚠️ 推送异常: {exc}")


if __name__ == "__main__":
    opts = parse_notify_args(sys.argv[1:])
    print(f"options: {opts}")
