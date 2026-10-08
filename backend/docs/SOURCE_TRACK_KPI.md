# 序1 · 样本卫生与 source 分轨 KPI

生成日：2026-10-02（Asia/Shanghai）。**仅供观察，不构成投资建议。**

## 硬规则

计入「真 LLM」样本须同时满足：

1. `source` / `pick_source` = `llm_rerank`（真调用成功，非 fallback）
2. 完整买卖腿：T+1 开盘买 → T+2 开盘卖，可结算（`status=settled`）
3. `n=5` 满篮

## 分轨

| track | 含义 |
|---|---|
| `llm_rerank` | 真 LLM Top5 |
| `rule_order` | 策略显示序并集前 5（非 LLM） |
| `asof_replay` | asof_* 事后回放 |
| `fallback_*` | LLM 失败后的 fallback（如 `fallback_rule_order`） |
| `multi_hit_shadow` | 旁路影子（`_shadow/*.multi_hit.json`），不进主 KPI |
| `paused` / `coverage_fail` / `other` | 空窗 / 覆盖门禁 / 其它 |

## 产品口径 vs 真 LLM

- **实际推荐 / 全部回溯**（日历大数字）：产品混轨（含 live + 回溯补算），**禁止**标成 `llm_rerank`。
- **真 LLM**：只看 `watch_calendar.json → kpi_by_source.true_llm` 或 `data/source_track_kpi/YYYY-MM.json`。

## 材料对照（2026-09）

| 口径 | 天数 | `eq_sum` 合计% |
|---|---:|---:|
| 真 `llm_rerank` settled | 11 | **+31.4756** |
| 产品日历混轨（不复权） | 12 | **≈ −1.90** |
| asof + rule 污染 2 日 | 2 | **−10.9464** |

脚本：`scripts/source_track_kpi.py`  
复现：`source_track_kpi.py --reproduce-sep-materials <materials raw/daily_picks>`

## 验收复现

```bash
# 精确对齐材料表（推荐）
.venv/bin/python scripts/source_track_kpi.py \
  --reproduce-sep-csv docs/sep2026_daily_compare.csv \
  --sep-summary docs/sep2026_summary.ref.json

# 用材料 pick source + 现网日历结算（口径会因后续补算日数而与材料 11 日不完全一致）
.venv/bin/python scripts/source_track_kpi.py \
  --reproduce-sep-materials /path/to/raw/daily_picks
```

期望：`acceptance_match=true` ⇒ 真 LLM 11 日 +31.4756；asof+rule 2 日 −10.9464。
