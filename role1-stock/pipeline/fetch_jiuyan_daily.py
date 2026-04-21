# -*- coding: utf-8 -*-
"""
韭研公社每日异动数据抓取

站点已改为首屏 SSR 不注入个股列表，改为调用 app API：
  POST /jystock-app/api/v1/action/field  — 板块列表
  POST /jystock-app/api/v1/action/list   — 某板块个股（需 action_field_id 蛇形命名）

Cookie / token 失效时更新下方 COOKIE、TOKEN（从浏览器已登录态 Network 复制）。
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
import requests

from _paths import REVIEW_DIR

# ============ 更新这里（失效时从浏览器 Network 复制） ============
COOKIE = (
    "SESSION=OWQwYTdkNjktNjY3OC00OWE1LWIxNmQtMWM4MWNkNmE0NTEz; "
    "Hm_lvt_58aa18061df7855800f2a1b32d6da7f4=1776327037; "
    "Hm_lpvt_58aa18061df7855800f2a1b32d6da7f4=1776347663"
)
# 请求头 token（与 Cookie 并列出现；过期则与 SESSION 一并更新）
TOKEN = "24e5a1c1d35d15b510b14babab4b8560"
# PC 网页对应 platform=3（与浏览器一致）
PLATFORM = "3"
# ================================================================

JY_API_BASE = "https://app.jiuyangongshe.com/jystock-app"

OUT_DIR = REVIEW_DIR
TODAY = datetime.now().strftime("%Y-%m-%d")

LIST_PAGE_SIZE = 80


def _plate_num_display(num) -> str:
    """接口里板数 num 为空或 None 时视为首板。"""
    if num is None:
        return "首板"
    if isinstance(num, str) and not num.strip():
        return "首板"
    return str(num)


def _api_headers() -> dict:
    return {
        "Cookie": COOKIE,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://www.jiuyangongshe.com",
        "Referer": "https://www.jiuyangongshe.com/action",
        "platform": PLATFORM,
        "timestamp": str(int(time.time() * 1000)),
        "token": TOKEN,
    }


def _post_json(path: str, body: dict, timeout: float = 60) -> dict:
    url = JY_API_BASE + path
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(url, headers=_api_headers(), json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def fetch_action_fields(trade_date: str) -> list:
    """板块元数据列表（含 action_field_id、name、reason 等）。"""
    j = _post_json("/api/v1/action/field", {})
    msg = (j.get("msg") or "").strip()
    err = j.get("errCode")
    data = j.get("data")
    if err and str(err) != "0" and err is not None:
        raise RuntimeError(f"action/field 业务错误 errCode={err} msg={msg or j}")
    if msg and "版本过低" in msg:
        raise RuntimeError(f"action/field: {msg}（请检查 platform/token 是否与浏览器一致）")
    if not data:
        raise RuntimeError(f"action/field 无 data: {j}")
    return data


def _skip_field(item: dict) -> bool:
    """跳过简图、全部（去重）；无板块 id 的条目。"""
    name = (item.get("name") or "").strip()
    afid = (item.get("action_field_id") or "").strip()
    if name == "简图":
        return True
    if name == "全部":
        return True
    if not afid:
        return True
    return False


def fetch_stocks_for_field(action_field_id: str, trade_date: str) -> list:
    """分页拉取某板块下全部个股（API 返回结构与旧 HTML 解析一致：code/name/article.action_info）。"""
    rows = []
    start = 0
    sorts = {"sort_price": 0, "sort_range": 0, "sort_time": 0}
    while True:
        body = {
            "action_field_id": action_field_id,
            "date": trade_date,
            "start": start,
            "limit": LIST_PAGE_SIZE,
            **sorts,
        }
        j = _post_json("/api/v1/action/list", body, timeout=90)
        msg = (j.get("msg") or "").strip()
        if msg and "必填参数" in msg:
            raise RuntimeError(f"action/list 参数错误: {msg} body={body}")
        data = j.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(f"action/list 异常: {j}")
        batch = data.get("result") or []
        total = int(data.get("totalCount") or 0)
        rows.extend(batch)
        if not batch or len(rows) >= total:
            break
        start += len(batch)
    return rows


def build_field_list_and_flat_stocks(field_meta: list, trade_date: str):
    """返回与旧版兼容的 field_list + 扁平 stocks（用于 JSON 明细表）。"""
    field_list_out = []
    flat_stocks = []

    for meta in field_meta:
        if _skip_field(meta):
            continue
        afid = meta["action_field_id"].strip()
        fname = meta.get("name", "") or ""
        theme = (meta.get("reason") or "").strip()

        stocks_raw = fetch_stocks_for_field(afid, trade_date)
        block = {"name": fname, "theme": theme, "list": stocks_raw}
        field_list_out.append(block)

        for s in stocks_raw:
            art = s.get("article", {})
            info = art.get("action_info", {})
            exp = info.get("expound", "") or ""
            kw = exp.split("\n")[0] if exp else ""
            sr = info.get("shares_range")
            try:
                sr_f = float(sr) if sr is not None else 0.0
            except (TypeError, ValueError):
                sr_f = 0.0
            flat_stocks.append(
                {
                    "板块": fname,
                    "代码": s.get("code", ""),
                    "名称": s.get("name", ""),
                    "涨停时间": info.get("time", ""),
                    "板数": _plate_num_display(info.get("num")),
                    "天数": info.get("day", ""),
                    "价格": round((info.get("price") or 0) / 100, 2),
                    "涨幅%": round(sr_f / 100, 2),
                    "关键词": kw,
                    "详细说明": exp,
                }
            )

    if not field_list_out:
        raise RuntimeError("未得到任何板块数据（可能 TOKEN/SESSION 失效或被风控）")

    return flat_stocks, field_list_out


def save_outputs(stocks: list, field_list: list, target_date: str):
    print("[保存] 写入 JSON / MD ...")
    json_path = OUT_DIR / f"韭研异动_{target_date}.json"
    json_path.write_text(json.dumps(stocks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      JSON → {json_path.name}")

    lines = [f"# 韭研公社异动解析 {target_date}", f"共 {len(field_list)} 板块 / {len(stocks)} 只", ""]
    for field in field_list:
        fname = field.get("name", "")
        theme = field.get("theme", "")
        fstocks = field.get("list", [])
        lines.append(f"## {fname}（{len(fstocks)}只）")
        if theme:
            lines.append(f"> **催化**：{theme}")
        lines.append("")
        lines.append("| 代码 | 名称 | 板数 | 涨停时间 | 价格 | 涨幅 | 关键词 |")
        lines.append("|------|------|------|---------|------|------|------|")
        for s in fstocks:
            info = s.get("article", {}).get("action_info", {})
            kw = (info.get("expound") or "").split("\n")[0][:30]
            price = round((info.get("price") or 0) / 100, 2)
            pct_raw = info.get("shares_range")
            try:
                pct = round(float(pct_raw) / 100, 2) if pct_raw is not None else 0.0
            except (TypeError, ValueError):
                pct = 0.0
            lines.append(
                f"| {s.get('code','')} | {s.get('name','')} | {_plate_num_display(info.get('num'))} "
                f"| {info.get('time','')} | {price} | {pct}% | {kw} |"
            )
        lines.append("")

    md_path = OUT_DIR / f"韭研异动_{target_date}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"      MD  → {md_path.name}")
    return md_path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default=TODAY,
        help="目标日期，支持 YYYYMMDD 或 YYYY-MM-DD；历史日期优先复用已有文件",
    )
    return parser.parse_args()


def normalize_date(value: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise ValueError(f"不支持的日期格式：{value}")


def main():
    args = parse_args()
    target_date = normalize_date(args.date)
    target_md = OUT_DIR / f"韭研异动_{target_date}.md"
    target_json = OUT_DIR / f"韭研异动_{target_date}.json"

    print("=" * 60)
    print(f"韭研公社异动抓取  {target_date}")
    print("=" * 60)

    if target_date != TODAY and target_md.exists() and target_json.exists():
        print(f"[INFO] 历史日期 {target_date} 已存在落盘文件，直接复用。")
        print(f"\n完成！输出文件：{target_md}")
        return

    try:
        if target_date != TODAY:
            raise RuntimeError(
                f"历史日期 {target_date} 暂不支持在线回抓；请先提供或保留已有的 "
                f"`韭研异动_{target_date}.md/.json` 文件。"
            )

        print("[1/3] POST api/v1/action/field ...")
        meta = fetch_action_fields(target_date)
        print(f"      板块元数据 {len(meta)} 条")

        print("[2/3] 按板块 POST api/v1/action/list 拉取个股 ...")
        stocks, field_list = build_field_list_and_flat_stocks(meta, target_date)
        print(f"      共 {len(field_list)} 个板块，{len(stocks)} 只个股")

        md_path = save_outputs(stocks, field_list, target_date)
        print(f"\n完成！输出文件：{md_path}")
    except Exception as e:
        print(f"\n[错误] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
