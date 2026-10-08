# POST /api/nl-analyze + `/ask` UI shell

Thin HTTP Analyze API for 巴小卡 NL 问询.

**Architecture（冻结 · Scheme A · skill_direct）**

`POST /api/nl-analyze` 内跑 **服务端 Agent 环**：LLM function-calling 循环调用 Quant Buddy HTTP 工具；密钥仅服务端；最终压成报告 JSON。

**废除**

- Intent 主路径：`quote` / `screen` / `report` 硬路由作为业务决策
- 冻死 `buildScreenFormulas` 作为筛选唯一代码分支（8 条公式仅作 few-shot）
- `unsupported_intent` 对回测的拒绝
- 调用 QBS 前对筛选/回测句的本地 `no_match`

**可选启发式**：极短单票行情句可先试一次 `fastQuery`，失败再进完整环——**不得**作为唯一路径，也不得对筛选句 `no_match`。

```
用户 query
  → POST /api/nl-analyze
  → Agent Loop (LLM + tools=QBS HTTP)
       ├─ new_session / fast_query / confirm_data_multi
       ├─ run_multi_formula / read_data / render_chart [/ render_kline]
       └─ finish_report → Report JSON
  → /ask 按 artifacts 渲染（表 / 序列 / 图）
```

## Tools（MVP）

Base `https://www.quantbuddy.cn/skill` · `Authorization: Bearer`

| 工具 | HTTP | 用途 |
| --- | --- | --- |
| `new_session` | `POST /session/begin` | 拿 `task_id` |
| `fast_query` | `POST /fastQuery` | snapshot \| window \| report |
| `confirm_data_multi` | `POST /confirmDataMulti` | 确认 PE/ROE 等 |
| `run_multi_formula` | **优先** sync `POST /runMultiFormulaBatch` | 选股/因子/回测（必带 `task_id`） |
| `read_data` | `POST /readData` | ids = **data_id** only |
| `render_chart` | `POST /renderChart` | PNG base64 |
| `render_kline` | `POST /renderKLine` | 单票 K 线（可选） |

System 硬规则：严禁客服式「请提供代码/名称」；无 ticker 仍须 `fast_query`（user_query 原话，assets 可空）；**禁止把指标名当 assets / 禁止擅自换成 881001·万得全A**；报告成功渲染指标表（指标/值/单位/报告期），空行情三列表不展示；`finish_report` 前须 ≥1 次成功数据工具。\n\nSystem 硬规则：公式一条一元素；引用数据名双引号；`板块(万得全A)` 不加引号；回测 `begin_date` 显式；`force_reusable_array` 保活；max_steps≈8；总超时 180–300s（对齐 nginx）。

## Routes

| path | notes |
| --- | --- |
| `GET /ask` | NL 问询 UI（artifacts：表/序列/图；无 intent 布局切换） |
| `GET /analyze` | 302 → `/ask` |
| `POST /api/nl-analyze` | 结构化 Report JSON |

## Request

```json
{ "query": "回测低 PE + 高 ROE 组合，相对沪深 300 画净值", "assets": [], "locale": "zh-CN" }
```

## Response

```json
{
  "ok": true,
  "report": {
    "title": "string",
    "summary_md": "string",
    "sections": [{ "heading": "string", "body_md": "string" }],
    "tables": [{ "name": "string", "columns": [], "rows": [] }],
    "series": [{ "name": "NAV", "dates": [], "values": [] }],
    "charts": [{ "name": "净值对比", "mime": "image/png", "data_base64": "...", "url": null }],
    "sources": [{ "provider": "quantbuddy", "tool": "run_multi_formula", "task_id": "..." }],
    "tool_trace": [{ "step": 1, "tool": "confirm_data_multi", "ok": true }],
    "disclaimer": "仅供观察/教育，不构成投资建议。",
    "latency_ms": 0
  },
  "meta": {
    "mode": "skill_direct",
    "model": "...",
    "steps": 5,
    "ru_used": null,
    "as_of": null
  }
}
```

- **不要求**对外 `intent` 字段
- API 保留 `sources`；`/ask` **不渲染**「来源」块
- KPI 卡片仅当自然出现可用行情数字时展示

## Env（names only）

| env var | role |
| --- | --- |
| `QBS_API_KEY` / `QUANT_BUDDY_API_KEY` | Bearer for Quant Buddy |
| `LLM_API_KEY` / `OPENAI_API_KEY` | Chat completions + tools |
| `LLM_API_BASE` / `LLM_BASE_URL` / `OPENAI_BASE_URL` | Completions base |
| `LLM_MODEL` / `OPENAI_MODEL` | Model id |

## `/ask` UI

有啥渲染啥：`tables`、`series`（简易 SVG）、`charts` 为 `<img src="data:image/png;base64,...">`。无 intent 布局开关。Badge「智能分析」。

## Acceptance（tencent `:8080`）

1. `回测低 PE + 高 ROE 组合，相对沪深 300 画净值` → 200，`meta.mode=skill_direct`，summary 含净值/超额 + 表和/或图；**不得**返回「全A筛选·Top10 / 放量突破」模板
2. 茅台行情仍出数
3. 全A筛选句不因无 ticker 404

## Curl

```bash
# backtest (skill_direct)
curl -sS -m 300 -X POST http://<SERVER_HOST>:8080/api/nl-analyze \
  -H 'Content-Type: application/json' \
  -d '{"query":"回测低 PE + 高 ROE 组合，相对沪深 300 画净值","locale":"zh-CN"}'

# quote
curl -sS -X POST http://<SERVER_HOST>:8080/api/nl-analyze \
  -H 'Content-Type: application/json' \
  -d '{"query":"查一下贵州茅台最新收盘价、涨跌幅和成交额。","locale":"zh-CN"}'

# screen (no pre-QBS no_match)
curl -sS -m 300 -X POST http://<SERVER_HOST>:8080/api/nl-analyze \
  -H 'Content-Type: application/json' \
  -d '{"query":"筛选今天 14:30 全 A 股中，近 60 个交易日创新高、成交额高于过去 20 日均值 2 倍、且涨幅排名靠前的公司。","locale":"zh-CN"}'
```

Page: http://<SERVER_HOST>:8080/ask

Build id: `nl-analyze-skill-direct-0.5.3`

## Out of scope

- 官方 Python skill 整包嵌入
- Keys in frontend
