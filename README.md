# 巴小卡（bxk-trader）

巴小卡是一个 **A 股观察 / 选股平台**：后端每日收盘后扫描全市场技术形态，结合 LLM 复排生成观察名单，
并跟踪次日表现；前端以 Cloudflare Worker 提供看板（观察日历、热力图、新闻、智能问答等）。

> ⚠️ **免责声明**：本项目仅供学习与市场观察，**不构成任何投资建议**。股市有风险，投资需谨慎。

## 目录结构

```
.
├── backend/   # Python 后端（选股、行情同步、LLM 复排、日历/热力图导出、推送脚本）
│   ├── sequoia_x/   # 核心包：配置、数据引擎、策略、通知
│   ├── scripts/     # 定时任务与工具脚本（run_*.sh、sync_today_*.py、llm_rerank.py 等）
│   ├── tests/
│   ├── docs/
│   ├── main.py · pyproject.toml · uv.lock · .env.example
│   └── LICENSE · NOTICE.md   # 上游 Sequoia-X 的 MIT 许可与署名
└── web/       # TypeScript Cloudflare Worker 前端
    ├── src/         # index.ts、heatmap.ts
    ├── docs/
    └── package.json · wrangler.jsonc · tsconfig.json
```

## 快速开始

后端（需 [uv](https://github.com/astral-sh/uv)）：

```bash
cd backend
cp .env.example .env      # 填写自己的 LLM_API_KEY、飞书 Webhook 等
uv sync
uv run python main.py
```

前端（需 Node.js）：

```bash
cd web
npm install
# 本地密钥放在 .dev.vars（已被 .gitignore 忽略），如 INGEST_TOKEN、LLM_API_KEY、QBS_API_KEY
export CLOUDFLARE_ACCOUNT_ID=<你的账户 ID>
npx wrangler dev
```

所有密钥只通过环境变量 / `.env` / `.dev.vars` / `wrangler secret` 提供，**不要提交到仓库**。
运行数据（`data/`、SQLite、日志等）不纳入版本控制。

## 来源与许可

`backend/` 派生自开源项目 [sngyai/Sequoia-X](https://github.com/sngyai/Sequoia-X)（MIT License），
在其基础上做了大量修改与扩展。上游版权与许可声明保留在 `backend/LICENSE` 与 `backend/NOTICE.md` 中。
