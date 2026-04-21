# Step 6: Merge and Render Daily Review

## Overview

`step6_merge_and_render.py` is the final step in the daily review workflow. It consolidates structured data from intermediate processing steps (step1-5) into a unified data dictionary and renders the complete daily review markdown file (`每日复盘表_YYYY-MM-DD.md`).

## Workflow

```
Step1 (Base Market Data)   ─┐
Step2 (Limit Statistics)   ──┼─> Merged Data ──> Render Markdown ──> 每日复盘表_YYYY-MM-DD.md
Step3 (Fundamentals)       ──┤
Step4 (Auction Data)       ──┤
Step5 (Rotation Analysis)  ─┘
```

## Input Files

The script expects these JSON files in the `outputs/` directory:

| Step | File Name | Content |
|------|-----------|---------|
| 1 | `step1_base_data.json` | Market indices (SH, SZ, CYB), trading dates sequence, name mappings |
| 2 | `step2_limits_data.json` | Daily limit-up/down counts, market sentiment statistics |
| 3 | `step3_fundamentals_data.json` | Sector analysis, market structure fundamentals |
| 4 | `step4_auction_data.json` | Opening auction data, bidding signals, competitive data |
| 5 | `step5_rotation_data.json` | Theme/sector rotation patterns, intraday analysis |

If any file is missing, the script uses default empty values and continues processing.

## Output

**File**: `outputs/每日复盘表_YYYY-MM-DD.md`

A complete markdown daily review table with 11 sections:
1. Index review
2. Sectors and themes review
3. Limit-up/down and sentiment analysis
4. 660 stock analysis
5. Dragon-Tiger board analysis
6. News review
7. Trading review
8. Next-day if-then checklist (15 conditions)
9. Trading direction and stock pool
10. Position planning
11. Pre-market and auction observation

## Usage

### Basic Usage
```bash
python3 step6_merge_and_render.py --trade-date YYYYMMDD
```

### With Custom Timeout (for background processes)
```bash
python3 step6_merge_and_render.py --trade-date 20260407 --timeout 300
```

The script will wait up to `--timeout` seconds for step files to be generated (default: 300 seconds = 5 minutes). This allows coordination with background processes running steps 1-5.

### With Custom Output Path
```bash
python3 step6_merge_and_render.py --trade-date 20260407 --output /path/to/custom_output.md
```

## Parameters

| Parameter | Required | Format | Default | Description |
|-----------|----------|--------|---------|-------------|
| `--trade-date` | Yes | YYYYMMDD | — | Trading date to process (e.g., 20260407) |
| `--timeout` | No | Integer | 300 | Max seconds to wait for step files |
| `--output` | No | Path | Auto-generated | Custom output markdown path |

## Examples

### Example 1: Basic workflow
```bash
python3 step6_merge_and_render.py --trade-date 20260407
# Output: outputs/每日复盘表_2026-04-07.md
```

### Example 2: Extended timeout for background processes
```bash
# Run steps 1-5 in background, then wait for completion
python3 step6_merge_and_render.py --trade-date 20260407 --timeout 600
```

### Example 3: Direct integration
```bash
# Integrate into a pipeline with custom output
python3 step6_merge_and_render.py \
  --trade-date 20260407 \
  --timeout 300 \
  --output outputs/review_2026-04-07.md
```

## Features

### Robust File Waiting
- Polls for step output files with configurable timeout
- Continues with available data if files are missing
- Warns about missing steps but doesn't fail

### Data Merging
- Consolidates data from 5 independent steps
- Applies safe type conversion (handles NaN, None, invalid types)
- Uses sensible defaults for missing fields

### Markdown Rendering
- Generates complete markdown structure matching the official template
- Pre-populates data fields (indices, sentiment counts, etc.)
- Maintains consistent formatting for manual completion

### Utility Functions
- `_fmt_pct()` - Format percentages with configurable decimals
- `_fmt_volume()` - Format volume in billions (亿)
- `_fmt_currency()` - Format currency values
- `_safe_float()` - Safe numeric conversion

## Data Flow

```python
# Step files → Load → Merge → Render → Markdown
{
  "name_map": {...},           # From step 1
  "tdays": [...],              # From step 1
  "trade_date": "2026-04-07",  # From step 1
  "sh": {...},                 # From step 1 (Shanghai index)
  "limit_up_count": 53,        # From step 2
  "themes": {...},             # From step 5
  ...
}
  ↓
render_markdown(merged_data, trade_date)
  ↓
每日复盘表_2026-04-07.md
```

## Error Handling

The script handles:
- Invalid date formats (not YYYYMMDD)
- Missing step files (waits, then continues)
- Corrupt JSON (logs warning, uses empty dict)
- Invalid numeric types (converts to "—")
- Directory creation (creates parent directories as needed)

## Integration Points

### With Daily Review Workflow (v2)
- **Position**: After steps 1-5, before step 3 (manual analysis)
- **Can run**: In parallel with step 2 (AI analysis)
- **Timeout coordination**: Use `--timeout 300` when steps 1-5 run as background jobs

### Command Line Integration
```bash
# Run step 1 in background
python step1_fetch_base_data.py --trade-date 20260407 &

# Run step 6 with extended timeout (waits for step 1)
python step6_merge_and_render.py --trade-date 20260407 --timeout 300
```

## Troubleshooting

### Issue: File not found error
```
[WARNING] Step 2 file not found after 300s
```
**Solution**: Ensure steps 1-5 have been run before step 6, or increase `--timeout`.

### Issue: All step files missing
```
[WARNING] Missing steps (will use defaults): [1, 2, 3, 4, 5]
```
**Solution**: Run the step scripts first (steps 1-5).

### Issue: Output file not created
**Solution**: Check write permissions on `outputs/` directory.

## Performance

- **Typical execution time**: < 1 second (after files are available)
- **Memory usage**: < 50 MB (for all step data)
- **Waiting time**: Depends on `--timeout` and when step files appear

## Logging

All operations are logged to stdout with levels:
- `[INFO]` - Informational messages
- `[WARNING]` - Non-fatal issues (missing optional files)
- `[SUCCESS]` - Operation completed successfully
- `[ERROR]` - Fatal errors (printed to stderr)

## Future Enhancements

Possible improvements:
1. Support for parallel step execution with process coordination
2. Template customization via external config file
3. PDF generation integration (call `md_to_pdf.py` automatically)
4. Real-time progress updates for long timeouts
5. Backup/archival of generated markdown files
