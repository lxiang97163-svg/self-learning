# -*- coding: utf-8 -*-
"""Centralised configuration loader.

Priority order:
1. ``config.local.json`` in the project root (``三一传统策略/refactored/``
   or its parent). Never commit this file.
2. Environment variables: ``TUSHARE_TOKEN``, ``TUSHARE_MIN_TOKEN``,
   ``PUSHPLUS_TOKEN``, ``DXX_PHPSESSID``, ``DXX_SERVER_NAME_SESSION``.

If both tushare tokens are missing, :func:`load_config` raises
``RuntimeError`` with guidance on how to configure them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CONFIG_FILENAME = "config.local.json"
DEFAULT_SEARCH_DIRS = (
    Path(__file__).resolve().parent.parent,          # refactored/
    Path(__file__).resolve().parent.parent.parent,   # 三一传统策略/
)


@dataclass(frozen=True)
class DxxCookies:
    """Cookies required to scrape ``duanxianxia.com`` auction封单 page."""

    phpsessid: str = ""
    server_name_session: str = ""

    def is_complete(self) -> bool:
        return bool(self.phpsessid and self.server_name_session)

    def as_dict(self) -> dict:
        return {
            "PHPSESSID": self.phpsessid,
            "server_name_session": self.server_name_session,
        }


@dataclass(frozen=True)
class AppConfig:
    """Immutable configuration bundle shared by every strategy script."""

    tushare_token: str
    tushare_min_token: str
    pushplus_token: Optional[str] = None
    dxx_cookies: DxxCookies = field(default_factory=DxxCookies)
    enable_push: bool = True

    def can_push(self) -> bool:
        return self.enable_push and bool(self.pushplus_token)


_HELP_MESSAGE = (
    "\nTushare token 未配置。请任选其一完成配置：\n"
    "  1) 在 refactored/ 下创建 config.local.json（可参考 config.example.json）\n"
    "  2) 设置环境变量 TUSHARE_TOKEN / TUSHARE_MIN_TOKEN\n"
)


def _find_config_file() -> Optional[Path]:
    """Return the first ``config.local.json`` found in the search path."""

    for base in DEFAULT_SEARCH_DIRS:
        candidate = base / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _load_from_file(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"读取 {path} 失败: {exc}") from exc


def _coalesce(primary: Optional[str], fallback_env: str) -> str:
    if primary:
        return primary
    return os.environ.get(fallback_env, "") or ""


def load_config() -> AppConfig:
    """Load configuration from file then environment."""

    file_data: dict = {}
    cfg_path = _find_config_file()
    if cfg_path is not None:
        file_data = _load_from_file(cfg_path)

    tushare_token = _coalesce(file_data.get("tushare_token"), "TUSHARE_TOKEN")
    tushare_min_token = _coalesce(file_data.get("tushare_min_token"), "TUSHARE_MIN_TOKEN")

    if not tushare_token or not tushare_min_token:
        raise RuntimeError(_HELP_MESSAGE)

    pushplus_token = _coalesce(file_data.get("pushplus_token"), "PUSHPLUS_TOKEN") or None

    dxx_raw = file_data.get("dxx_cookies") or {}
    dxx = DxxCookies(
        phpsessid=_coalesce(dxx_raw.get("PHPSESSID"), "DXX_PHPSESSID"),
        server_name_session=_coalesce(
            dxx_raw.get("server_name_session"), "DXX_SERVER_NAME_SESSION"
        ),
    )

    enable_push = bool(file_data.get("enable_push", True))

    return AppConfig(
        tushare_token=tushare_token,
        tushare_min_token=tushare_min_token,
        pushplus_token=pushplus_token,
        dxx_cookies=dxx,
        enable_push=enable_push,
    )


def init_tushare_clients():
    """Build the two tushare clients (``pro``, ``pro_min``) using loaded config.

    Returns a 3-tuple ``(config, pro, pro_min)``. Import is deferred so this
    module can be used in environments where chinadata is not installed.
    """

    import chinadata.ca_data as ts  # type: ignore import-not-found
    import chinamindata.min as tss  # type: ignore import-not-found

    cfg = load_config()
    ts.set_token(cfg.tushare_token)
    tss.set_token(cfg.tushare_min_token)
    return cfg, ts.pro_api(), tss.pro_api()


if __name__ == "__main__":  # Manual smoke test
    try:
        cfg = load_config()
    except RuntimeError as exc:
        print(f"[config] 加载失败: {exc}")
    else:
        print("[config] 加载成功")
        print(f"  tushare_token: {'*' * 4}{cfg.tushare_token[-4:]}")
        print(f"  pushplus配置: {'是' if cfg.pushplus_token else '否'}")
        print(f"  dxx cookie 完整: {cfg.dxx_cookies.is_complete()}")
        print(f"  允许推送: {cfg.can_push()}")
