#!/bin/bash
#
# 步骤4-5 集成运行脚本
# 使用说明：
#   ./run_step4_step5.sh 20260305
#   ./run_step4_step5.sh 20260305 "20260227,20260228,20260301,20260304,20260305"
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TRADE_DATE="${1:-20260305}"
PAST_5_DAYS="${2:-}"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}步骤4-5 集成运行${NC}"
echo -e "${GREEN}交易日期：${TRADE_DATE}${NC}"
if [ -n "$PAST_5_DAYS" ]; then
    echo -e "${GREEN}过去5个交易日：${PAST_5_DAYS}${NC}"
else
    echo -e "${YELLOW}（过去5个交易日将自动查询）${NC}"
fi
echo -e "${GREEN}========================================${NC}"
echo

# Step 4: 竞价成交数据
echo -e "${GREEN}[步骤4] 获取竞价成交数据...${NC}"
python3 step4_fetch_auction.py \
    --trade-date "$TRADE_DATE" \
    --output "step4_auction_data_${TRADE_DATE}.json"

if [ -f "step4_auction_data_${TRADE_DATE}.json" ]; then
    echo -e "${GREEN}✅ 步骤4 完成${NC}"
    echo "输出文件：step4_auction_data_${TRADE_DATE}.json"
    echo
else
    echo -e "${RED}❌ 步骤4 失败${NC}"
    exit 1
fi

# Step 5: 轮动热力追踪
echo -e "${GREEN}[步骤5] 生成轮动热力追踪...${NC}"

if [ -n "$PAST_5_DAYS" ]; then
    python3 step5_fetch_rotation.py \
        --trade-date "$TRADE_DATE" \
        --past-5-days "$PAST_5_DAYS" \
        --output "step5_rotation_data_${TRADE_DATE}.json"
else
    python3 step5_fetch_rotation.py \
        --trade-date "$TRADE_DATE" \
        --output "step5_rotation_data_${TRADE_DATE}.json"
fi

if [ -f "step5_rotation_data_${TRADE_DATE}.json" ]; then
    echo -e "${GREEN}✅ 步骤5 完成${NC}"
    echo "输出文件：step5_rotation_data_${TRADE_DATE}.json"
    echo
else
    echo -e "${RED}❌ 步骤5 失败${NC}"
    exit 1
fi

# 总结
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ 所有步骤完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo
echo -e "${YELLOW}输出文件：${NC}"
echo "  1. step4_auction_data_${TRADE_DATE}.json"
echo "  2. step5_rotation_data_${TRADE_DATE}.json"
echo
echo -e "${YELLOW}查看输出：${NC}"
echo "  cat step4_auction_data_${TRADE_DATE}.json | jq '.auc_text'"
echo "  cat step5_rotation_data_${TRADE_DATE}.json | jq '.rotation_content' | head -20"
echo

# 可选：合并输出
if command -v jq &> /dev/null; then
    echo -e "${YELLOW}合并两个输出文件...${NC}"
    jq -s '{auction: .[0], rotation: .[1]}' \
        "step4_auction_data_${TRADE_DATE}.json" \
        "step5_rotation_data_${TRADE_DATE}.json" \
        > "merged_${TRADE_DATE}.json"
    echo -e "${GREEN}✅ 合并完成：merged_${TRADE_DATE}.json${NC}"
fi
