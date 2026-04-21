# 优化文档索引

本目录为 `generate_review_from_tushare` 性能优化相关文档入口，与 `COMPLETE_PROJECT_SUMMARY.md` 中的文件清单一致。

| 文档 | 说明 |
|------|------|
| [COMPLETE_PROJECT_SUMMARY.md](./COMPLETE_PROJECT_SUMMARY.md) | 完整项目总结 |
| [FINAL_SUMMARY.md](./FINAL_SUMMARY.md) | 会话总结 |
| [OPTIMIZATION_RESULTS.md](./OPTIMIZATION_RESULTS.md) | 最终成果与测试 |
| [PERFORMANCE_ANALYSIS.md](./PERFORMANCE_ANALYSIS.md) | 性能瓶颈分析 |
| [ARCHITECTURE_REFACTORING.md](./ARCHITECTURE_REFACTORING.md) | 架构重构设计 |
| [OPTIMIZATION_PLAN.md](./OPTIMIZATION_PLAN.md) | 方案对比与实施路线 |

`outputs/` 下提供同名副本，便于与脚本同目录查阅。

**运行方案 B**：在 `jumpingnow_all` 下执行  
`python3 orchestrate_parallel_steps.py --trade-date YYYYMMDD --workers 5`
