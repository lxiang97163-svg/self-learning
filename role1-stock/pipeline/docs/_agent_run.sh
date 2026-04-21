#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1
# 避免 chinadata 龙虎榜逐只 top_inst 长时间阻塞
export REVIEW_USE_AK_LHB_NET=1
python3 -u generate_review_from_tushare.py --trade-date 20260401 2>&1 | tee _gen_review_0401.log
echo "EXIT:$?" >> _gen_review_0401.log
