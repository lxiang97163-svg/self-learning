# -*- coding: utf-8 -*-
"""一键顺序跑全部策略 (或选子集)。

用法示例::

    python strategies/run_all.py                # 全部
    python strategies/run_all.py --parallel     # 并行
    python strategies/run_all.py --only jingjia_31_duanban tidui_baoliang_yihong
    python strategies/run_all.py --no-push      # 所有脚本都 --no-push
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, List, Sequence

logger = logging.getLogger(__name__)


STRATEGY_ORDER = (
    "jingjia_31_duanban",
    "tidui_baoliang_yihong",
    "danhe_daidui",
    "sector_scan_9431",
    "tidui_fupan",
    "zhaban_diji",  # Fix LOW #16: was missing from STRATEGY_ORDER
)


def _run_one(script_path: Path, extra_argv: Sequence[str]) -> int:
    argv = [sys.executable, str(script_path), *extra_argv]
    logger.info("\n>>> RUN %s %s", script_path.name, " ".join(extra_argv))
    result = subprocess.run(argv, check=False)
    logger.info("<<< EXIT %s: %d", script_path.name, result.returncode)
    return result.returncode


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", action="store_true", help="并行执行 (默认串行)")
    parser.add_argument("--only", nargs="+", choices=STRATEGY_ORDER, help="仅执行指定脚本")
    parser.add_argument("--no-push", action="store_true", help="传递 --no-push 到每个子脚本")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="传递 --output-file=<dir>/<name>.txt 到每个子脚本",
    )
    args, passthrough = parser.parse_known_args(list(argv) if argv is not None else None)

    base_dir = Path(__file__).resolve().parent
    selected: List[str] = list(args.only) if args.only else list(STRATEGY_ORDER)

    def _extra_for(script_name: str) -> List[str]:
        extra: List[str] = []
        if args.no_push:
            extra.append("--no-push")
        if args.output_dir:
            out = Path(args.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            extra.extend(["--output-file", str(out / f"{script_name}.txt")])
        extra.extend(passthrough)
        return extra

    exit_code = 0
    if args.parallel:
        with ThreadPoolExecutor(max_workers=min(4, len(selected))) as executor:
            futures = [
                executor.submit(_run_one, base_dir / f"{name}.py", _extra_for(name))
                for name in selected
            ]
            for f in futures:
                exit_code = exit_code or f.result()
    else:
        for name in selected:
            rc = _run_one(base_dir / f"{name}.py", _extra_for(name))
            exit_code = exit_code or rc

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
