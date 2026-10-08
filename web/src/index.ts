import { HEATMAP_COPY, HEATMAP_UI, heatmapView, isHeatmapPayload } from "./heatmap";
interface Env {
  PICKS: R2Bucket;
  INGEST_TOKEN?: string;
  /** Quant Buddy Skill API key (prefer QBS_API_KEY). */
  QBS_API_KEY?: string;
  QUANT_BUDDY_API_KEY?: string;
  /** Chat completions for NL report writer (optional; template fallback if missing). */
  LLM_API_KEY?: string;
  LLM_API_BASE?: string;
  LLM_BASE_URL?: string;
  LLM_MODEL?: string;
  OPENAI_API_KEY?: string;
  OPENAI_BASE_URL?: string;
  OPENAI_MODEL?: string;
  /** Local dsh-bridge (:8789 → dsh web :8788). Default http://127.0.0.1:8789 */
  DSH_BRIDGE_URL?: string;
  /** nl-analyze path: "dsh" (default, official skill) | "skill_direct" (legacy Worker Agent). */
  NL_ANALYZE_MODE?: string;
}

interface Strategy { name: string; symbols: string[] }
interface QuoteSnapshot {
  close: number | null;
  chg_pct: number | null;
  volume: number | null;
  vol_chg_pct: number | null;
}
interface PickMeta {
  industry: string | null; // baostock national industry (fallback display)
  board: string;
  sw_l1?: string | null;
  sw_l1_code?: string | null;
  sw_l2?: string | null;
  sw_l2_code?: string | null;
  industry_group?: string | null; // homepage industry view key (申万)
}
interface DailyPickSymbol {
  code: string;
  name: string;
  reason?: string;
  explain?: string;
}
interface DailyPicksBlock {
  date: string;
  source: string;
  symbols: DailyPickSymbol[];
  /** "ok" | "paused" (0.12.4). pause_reason is data-only, never rendered. */
  pick_status?: string;
  paused?: boolean;
  pause_reason?: string;
  attempts?: number;
  pick_status_at?: string;
  /** 0.13.0 dual model: model id / display label / model key / backfill flag. */
  model?: string;
  model_key?: string;
  label?: string;
  backfill?: boolean;
  /** 0.13.3: real signal-day change for backfill picks (percent units, close vs previous close).
   *  Shown only when as_of === date; otherwise the card shows no change at all. */
  signal_day_quotes?: { as_of?: string; unit?: string; source?: string; items?: Record<string, { prev_date?: string; prev_close?: number; close?: number; chg_pct?: number }> };
}
interface LatestPicks {
  generated_at: string;
  /** Signal-day fields may be supplied by different latest.json producers. */
  signal_day?: string;
  as_of?: string;
  date?: string;
  mode: string;
  strategies: Strategy[];
  names?: Record<string, string>;
  quotes?: Record<string, QuoteSnapshot>;
  // Grouping metadata lives beside quotes so quote payloads remain numeric-only.
  meta?: Record<string, PickMeta>;
  /** Top5 from write_daily_picks — reason/explain for homepage 推荐理由. */
  daily_picks?: DailyPicksBlock;
  /** 0.13.0: per-model Top5 blocks (models.gpt mirrors daily_picks). */
  models?: Record<string, DailyPicksBlock | undefined>;
}
interface OhlcvBar {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
}
interface ProfitReport {
  stat_date: string | null;
  pub_date: string | null;
  revenue: number | null;
  net_profit: number | null;
  eps_ttm: number | null;
  roe: number | null;
  yoy_revenue: number | null;
  yoy_net_profit: number | null;
}
interface StockDetail {
  symbol: string;
  name: string | null;
  market: string;
  industry: string | null;
  board?: string;
  ipo_date: string | null;
  main_business: string | null;
  as_of: string;
  ohlcv_60d: OhlcvBar[];
  last_report: ProfitReport | null;
  recent_reports: ProfitReport[];
  picked_strategies: string[];
}

interface WatchSymbol { code: string; name: string }
interface WatchReviewFactor {
  code: string;
  [key: string]: unknown;
}
interface WatchReview {
  tags: string[];
  factors?: WatchReviewFactor[];
  reasons: string[];
  asof?: string;
}
interface WatchStock extends WatchSymbol {
  buy_open: number | null;
  sell_open: number | null;
  chg_pct: number | null;
  review?: WatchReview | null;
  /** LLM 人话推荐理由（distinct from review.reasons 下跌复盘）. */
  reason?: string;
  explain?: string;
}
interface WatchDay {
  date: string;
  status?: "settled" | "pending" | "paused";
  buy_date?: string | null;
  sell_date?: string | null;
  eq_avg_chg_pct: number | null;
  eq_sum_chg_pct?: number | null;
  cum_eq_avg_chg_pct?: number;
  stocks: WatchStock[];
  n?: number;
  shadow_missing?: boolean;
  pick_origin?: string;
  /** Per-day daily_picks.source (not displayed). */
  pick_source?: string;
  source_track?: string;
  /** "ok" | "paused" (0.12.4). pause_reason is data-only, never rendered. */
  pick_status?: string;
  pause_reason?: string;
  attempts?: number;
  pick_status_at?: string;
  /** 0.13.0: model id that produced the day; backfill = 事后补算 (purple dot / 回溯 tag). */
  model?: string;
  backfill?: boolean;
  /** Future: day kept for reference but excluded from KPI totals. */
  exclude_from_totals?: boolean;
}
interface WatchTrack {
  id?: string;
  label?: string;
  source?: string;
  model?: string;
  /** gpt: days_ref="days" points at top-level days. */
  days?: WatchDay[];
  days_ref?: string;
  /** Archived live batches: kept verbatim, never in grid or totals. */
  archived_days?: WatchDay[];
}
interface WatchCalendar {
  symbols: WatchSymbol[];
  generated_at: string;
  note?: string;
  days: WatchDay[];
  default_track?: string;
  kpi_by_source?: Record<string, unknown>;
  tracks?: {
    llm?: WatchTrack;
    [key: string]: WatchTrack | undefined;
  };
}

type NewsCategory = "earnings" | "mna" | "legal" | "opinion";
interface NewsEvent {
  id: string;
  datetime: string;
  date: string;
  /** "day" = date-only source (no real clock); "minute" = source had HH:MM. */
  time_precision?: "day" | "minute";
  company: string;
  code: string;
  title: string;
  summary: string;
  source_name: string;
  source_url: string;
  category: NewsCategory;
  tags?: string[];
}
interface NewsByDay {
  total: number;
  earnings?: number;
  mna?: number;
  legal?: number;
  opinion?: number;
}
interface NewsEventsPayload {
  generated_at: string;
  scanned_at?: string;
  opinion_enabled?: boolean;
  note?: string;
  counts?: Record<string, number>;
  events: NewsEvent[];
  by_day?: Record<string, NewsByDay>;
}

const LATEST_KEY = "latest.json";
const WATCH_CALENDAR_KEY = "watch_calendar.json";
const NEWS_EVENTS_KEY = "news_events.json";
const HEATMAP_KEY = "heatmap.json";
const DETAIL_PREFIX = "details/";
const MAX_INGEST_BYTES = 5_000_000;
const WATCH_POOL = ["000626", "301072", "000700", "002868", "605088"] as const;
const STRATEGY_LABELS: Record<string, string> = {
  MaVolumeStrategy: "均线放量",
  TurtleTradeStrategy: "海龟突破",
  HighTightFlagStrategy: "高窄旗形",
  LimitUpShakeoutStrategy: "涨停洗盘",
  UptrendLimitDownStrategy: "上升跌停反包",
  RpsBreakoutStrategy: "RPS 相对强度突破",
  PrivatePlacementStrategy: "定增相关",
  BowlReboundStrategy: "碗口反弹",
};
interface StrategyHelp { first: string; second: string }
const STRATEGY_HELP: Record<string, StrategyHelp> = {
  TurtleTradeStrategy: {
    first: "收盘价创近 20 日新高，且当日阳线、真涨，成交额过亿。",
    second: "同时满足：收盘高于前 20 日最高价；成交额大于 1 亿；收盘高于开盘（阳线）；收盘高于昨收。这是收盘后的突破扫描，不是经典海龟「买入持有」系统；高开低走的阴线不会入选。",
  },
  MaVolumeStrategy: {
    first: "5 日均线刚金叉 20 日均线，且当日成交量明显放大。",
    second: "昨天还是短均线在长均线下方，今天翻到上方；同时今日成交量大于近 20 日均量的 1.5 倍。不是「股价在均线上方」就选，必须是当天刚金叉。",
  },
  HighTightFlagStrategy: {
    first: "前面涨得很猛，最近缩成窄幅整理，还缩量，且整理仍在高位。",
    second: "近 40 日高低振幅约超 60%，近 10 日振幅约低于 15%，整理低点仍在前期高点八成以上，今日量低于近 20 日均量的六成。不是债相关；也不是已向上突破，只是高位缩量整理形态。",
  },
  LimitUpShakeoutStrategy: {
    first: "昨天近似涨停，今天放量收阴，但最低价没跌破昨天收盘。",
    second: "昨收相对前日涨幅约达 9.5%；今日收阴、量大于昨量两倍，且最低价不低于昨收。不是「今天继续涨停」，而是涨停后的回踩确认扫描。",
  },
  UptrendLimitDownStrategy: {
    first: "大趋势仍向上（均线多头），今天却放量近似跌停。",
    second: "昨日 20 日均线高于 60 日均线；今日收盘相对昨收跌约 9.5% 或更多，且量大于 20 日均量两倍。不是推荐追跌停，语义是扫趋势里的错杀日。",
  },
  RpsBreakoutStrategy: {
    first: "近 120 日涨幅排全市场前约 10%，且收盘接近该期高点。",
    second: "按相对 120 日前收盘的涨幅做横截面排名，只留 RPS≥90 的票；同时今日收盘不低于近 120 日最高价的九成。是简化日频相对强度，不是欧奈尔原版全套。",
  },
  PrivatePlacementStrategy: {
    first: "最近 7 天有定向增发公告的股票。",
    second: "来自东方财富「全部增发」里发行方式为定向增发、发行日期在近 7 天内的标的。不看 K 线；接口失败时列表可能为空。",
  },
  BowlReboundStrategy: {
    first: "上升趋势里刚放过量阳线，价格回落到「碗口」中轴附近，且 KDJ 的 J 偏冷。",
    second: "知行短期趋势线仍在多空线上方；近约 30 个交易日里出现过放量阳线（量至少约前日两倍、收阳、总市值大于约 40 亿），且那段里最大量那天不能是阴线；J 值不超过约 20；现价落在短期与多空之间，或贴近其中一条。过滤 ST、退市、无量、近 30 日 J 过热。只做收盘选股信号，无自带卖点。结算：信号日收盘扫入池；次日开盘买、再下一日开盘卖；不复权计价。",
  },
};
const MODE_LABELS: Record<string, string> = { daily: "日常", backfill: "回填" };
const HOME_VIEWS = ["strategy", "industry", "board"] as const;
const WORKER_BUILD = "0.13.17";
const FALLBACK_NO_EXPLAIN = "规则排序、暂无解释";
const LABEL_EXPLAIN = "推荐理由";
// 0.13.0 dual model (same pool / prompt / top-5 / settlement; only the LLM differs).
/** Writer keys (0.13.17): Claude paused — keep unused Claude keys for later. */
const MODEL_GPT_NAME = "GPT-6.1 Sol";
const MODEL_GPT_SHORT = "GPT";
const MODEL_CLAUDE_NAME = "Claude Opus 5.5"; // unused while Claude hidden
const MODEL_CLAUDE_SHORT = "Claude"; // unused
const HEADER_MODEL_SUB = "{name} · {m} 月收益 {pct} · 含回溯 {n} 天";
const HEADER_MODEL_SUB_NO_BACKFILL = "{name} · {m} 月收益 {pct}";
const PICK_MODELS = [
  { key: "gpt", label: MODEL_GPT_NAME, short: MODEL_GPT_SHORT },
] as const;
/** Claude paused in UI/compute; type kept so historical track JSON still typechecks. */
type PickModelKey = "gpt" | "claude";
function pickModelKey(value: string | null | undefined): PickModelKey {
  // ?model=claude and localStorage claude → GPT view
  return "gpt";
}
function pickModelLabel(key: PickModelKey): string {
  if (key === "claude") return MODEL_CLAUDE_NAME; // unused path
  return MODEL_GPT_NAME;
}
const MODEL_STORAGE_KEY = "sx_pick_model";
/** No toggle — Claude/GPT switcher removed; only header_model_sub remains. */
const MODEL_SWITCH_CSS = `.model-bar{display:block;margin:18px 0 0;padding:10px 14px;border:1px solid #222930;border-radius:12px;background:#0b0f12;min-width:0}.model-sub{margin:0;color:#9ba5aa;font:500 12px/1.4 "PingFang SC",ui-monospace,SFMono-Regular,Menlo,Consolas,sans-serif;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}.model-sub.is-empty{color:#9aa8ff}.top5-model-sub{margin:0;color:#9ba5aa;font:500 12px/1.4 "PingFang SC",sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}@media(max-width:599px){.model-bar{margin-top:14px;padding:8px 12px}.model-sub,.top5-model-sub{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}}`;
function modelSwitchMarkup(_active: PickModelKey): string {
  // Switcher removed (设计师)
  return "";
}
function headerModelSubMarkup(): string {
  return `<section class="model-bar" aria-label="${escapeHtml(MODEL_GPT_NAME)}"><p class="model-sub" id="model-sub">—</p></section>`;
}
/** tip_backfill (writer final): calendar day-detail note for a backfill day. */
const TIP_BACKFILL = "这一天是事后补算的：只用到当天收盘为止的数据，按真实开盘价结算。";
/** detail_paused_body_backfill (0.13.5, writer final): body for a PAUSED day that is a backfill day
 *  (calendar day detail / latest-day pool / home Top5). Live paused days keep detail_paused_body. */
/** 0.13.6 dual-basis totals (PM 2026-09-29): 实际推荐 = live result where a live pick existed, backfill only where no live result; 全部回溯 = every day re-run. */
/** 0.13.7 (PM 2026-09-29 13:00): live = has a 15:05 live-log record (data: day.live_flag / day.actual_basis). Writer copy for the total hints. */
/** tip_backfill_early (0.13.8, writer final): early after-the-fact days whose data basis can't be verified (data: day.basis_verified === false). */
const TIP_BACKFILL_EARLY = "这一天是早期事后补算的。当时用到哪天的数据，现在已经无法核实，结果只能作参考。";
/** 0.13.9: exchange non-trading weekdays (read-only embed, same list as the pipeline's pick_guard / market_holidays). Future trading days render as "not yet". */
const MARKET_HOLIDAYS_2026 = ["2026-09-25","2026-10-01","2026-10-02","2026-10-05","2026-10-06","2026-10-07"]; // only future dates use it; past no-data days keep 休市
const LABEL_ACTUAL = "实际推荐";
const LABEL_RERUN = "全部回溯";
/** 0.13.11 densified calendar copy (writer frozen keys). */
const CARD_SUB = "含回溯 {n} 天 · 全部回溯 {pct}";
const CARD_SUB_NO_BACKFILL = "全部回溯 {pct}";
const RULES_LINE1 = "实际推荐按开盘前挂在页面上的结果算，没有的日子用回溯补上。";
const RULES_LINE2 = "● 表示回溯日，没点的是实时。仅供观察，不构成投资建议。";
const TIP_TWO_TOTALS = "实际推荐：有实时推荐的日子按实时结果算，其余日子用回溯补上。全部回溯：把每一天都按现在的流程重算一遍，只能作参考，不是当时真实的表现。";
const TIP_BACKFILL_LEGEND = "带淡紫点的是回溯补算的日子，没点的是当天实时选的。模型训练时可能见过这些行情，回溯结果仅供参考。仅供观察，不构成投资建议。";
const STRATEGY_TIMELINE = "T 15:05 扫盘推荐 → T+1 09:35 开盘买入 → T+2 09:35 开盘卖出结算";
const STRATEGY_DISCLAIMER = "仅供观察，不构成投资建议。";
const TIP_STRATEGY = "每天选出五只，次日开盘买入，再下一交易日开盘卖出结算。涨跌幅用不复权行情，五只相加再计入日合计，不算复利。仅供观察，不构成投资建议。";
const DETAIL_RERUN_TITLE = "回溯版（不计入实际推荐）";
const DETAIL_PAUSED_BODY_BACKFILL = "{date} 的回溯补算没有得出有效结果，这一天不计入收益合计。";
function detailPausedBodyBackfill(date: string): string {
  return DETAIL_PAUSED_BODY_BACKFILL.replace("{date}", date);
}
/** home_backfill_note (0.13.3, PM picked the writer's template): note above home Top5 cards of a backfill block.
 *  {n} = cards actually shown, {date} = that model's signal day. */
const HOME_BACKFILL_NOTE = "以下 {n} 只是事后补算的回溯结果，不是当天实时选出。只用到 {date} 收盘为止的数据，按真实开盘价结算。";
function homeBackfillNote(n: number, date: string): string {
  return HOME_BACKFILL_NOTE.replace("{n}", String(n)).replace("{date}", date);
}
/** empty_backfilling (0.13.1): 「{model} 的历史数据还在补算，稍后再来看。」 */
function emptyBackfillingCopy(label: string): string {
  return `${label} 的历史数据还在补算，稍后再来看。`;
}
type HomeView = typeof HOME_VIEWS[number];
// 申万一级展示序（电子后插入半导体；未分类末尾）。其它一级不强制展开二级。
const SW_INDUSTRY_ORDER: string[] = [
  "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "半导体", "汽车", "家用电器", "食品饮料",
  "纺织服饰", "轻工制造", "医药生物", "公用事业", "交通运输", "房地产", "商贸零售", "社会服务",
  "银行", "非银金融", "综合", "建筑材料", "建筑装饰", "电力设备", "机械设备", "国防军工",
  "计算机", "传媒", "通信", "煤炭", "石油石化", "环保", "美容护理",
];

const BOARD_GROUPS = [
  { name: "沪市主板", hint: "60 开头" },
  { name: "深市主板", hint: "SZ · 000 / 001 / 002 / 003…" },
  { name: "创业板", hint: "300 / 301 开头" },
  { name: "科创板", hint: "688 开头" },
  { name: "北交所", hint: "8 / 4 开头或 BJ" },
  { name: "其他", hint: "其他代码" },
] as const;
type BoardName = typeof BOARD_GROUPS[number]["name"];
const JSON_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8",
};
/** POST/GET /api/nl-analyze (+ jobs) CORS (same open policy as public GET JSON). */
const NL_ANALYZE_HEADERS = {
  ...JSON_HEADERS,
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};
/** Homepage + latest.json: short TTL + SWR (aligns with daily ~15:05 refresh). */
const PUBLIC_CACHE = "public, max-age=60, s-maxage=300, stale-while-revalidate=3600";
const CHIP_PREVIEW = 24;

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/" && request.method === "GET") return renderHome(env, url);
    if (url.pathname === "/calendar") {
      if (request.method !== "GET") return methodNotAllowed("GET");
      return renderCalendar(env, url);
    }
    if (url.pathname === "/news") {
      if (request.method !== "GET") return methodNotAllowed("GET");
      return renderNews(env);
    }
    if (url.pathname === "/heatmap") {
      if (request.method !== "GET") return methodNotAllowed("GET");
      return renderHeatmap(env);
    }

    const symbolMatch = url.pathname.match(/^\/s\/(\d{6})$/);
    if (symbolMatch) {
      if (request.method !== "GET") return methodNotAllowed("GET");
      return renderDetail(env, symbolMatch[1]);
    }
    if (url.pathname === "/api/latest.json") {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });
      if (request.method === "GET") return readObject(env, LATEST_KEY);
      return methodNotAllowed("GET, OPTIONS");
    }
    if (url.pathname === "/api/watch_calendar.json") {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });
      if (request.method === "GET") return readObject(env, WATCH_CALENDAR_KEY);
      return methodNotAllowed("GET, OPTIONS");
    }
    if (url.pathname === "/api/news_events.json") {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });
      if (request.method === "GET") return readObject(env, NEWS_EVENTS_KEY);
      return methodNotAllowed("GET, OPTIONS");
    }
    if (url.pathname === "/api/heatmap.json") {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });
      if (request.method === "GET") return readObject(env, HEATMAP_KEY);
      return methodNotAllowed("GET, OPTIONS");
    }
    const detailJsonMatch = url.pathname.match(/^\/api\/details\/(\d{6})\.json$/);
    if (detailJsonMatch) {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });
      if (request.method === "GET") return readObject(env, `${DETAIL_PREFIX}${detailJsonMatch[1]}.json`);
      return methodNotAllowed("GET, OPTIONS");
    }
    if (url.pathname === "/api/ingest") {
      if (request.method !== "PUT") return methodNotAllowed("PUT");
      {
        const key = url.searchParams.get("key");
        if (key === "watch_calendar") return ingestWatchCalendar(request, env);
        if (key === "news_events") return ingestNewsEvents(request, env);
        if (key === "heatmap") return ingestHeatmap(request, env);
        return ingestLatest(request, env);
      }
    }
    if (url.pathname === "/api/ingest/watch_calendar") {
      if (request.method !== "PUT") return methodNotAllowed("PUT");
      return ingestWatchCalendar(request, env);
    }
    if (url.pathname === "/api/ingest/news_events") {
      if (request.method !== "PUT") return methodNotAllowed("PUT");
      return ingestNewsEvents(request, env);
    }
    if (url.pathname === "/api/ingest/heatmap") {
      if (request.method !== "PUT") return methodNotAllowed("PUT");
      return ingestHeatmap(request, env);
    }
    const detailIngestMatch = url.pathname.match(/^\/api\/details\/(\d{6})$/);
    if (detailIngestMatch) {
      if (request.method !== "PUT") return methodNotAllowed("PUT");
      return ingestDetail(request, env, detailIngestMatch[1]);
    }
    // Path B: thin NL Analyze API → DSH bridge (async jobs) / skill_direct.
    if (url.pathname === "/api/nl-analyze") {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: NL_ANALYZE_HEADERS });
      if (request.method === "POST") return handleNlAnalyze(request, env);
      return methodNotAllowed("POST, OPTIONS");
    }
    const nlJobMatch = url.pathname.match(/^\/api\/nl-analyze\/jobs\/([A-Za-z0-9_-]+)$/);
    if (nlJobMatch) {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: NL_ANALYZE_HEADERS });
      if (request.method === "GET") return handleNlAnalyzeJob(env, nlJobMatch[1]);
      return methodNotAllowed("GET, OPTIONS");
    }
    if (url.pathname === "/ask") {
      if (request.method !== "GET") return methodNotAllowed("GET");
      return renderAskPage(url);
    }
    if (url.pathname === "/analyze") {
      // Frozen route is /ask; keep /analyze as redirect for old links.
      if (request.method !== "GET") return methodNotAllowed("GET");
      return new Response(null, { status: 302, headers: { Location: "/ask" + url.search } });
    }
    return html(pageShell(errorState("页面不存在", "请检查访问地址。")), 404);
  },
} satisfies ExportedHandler<Env>;

async function readObject(env: Env, key: string): Promise<Response> {
  const object = await env.PICKS.get(key);
  if (!object) return json({ error: `${key} not found` }, 404, JSON_HEADERS);
  const headers = new Headers(JSON_HEADERS);
  object.writeHttpMetadata(headers);
  headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Cache-Control", key === LATEST_KEY || key === HEATMAP_KEY ? PUBLIC_CACHE : "no-store");
  headers.set("ETag", object.httpEtag);
  return new Response(object.body, { headers });
}

async function readJson(env: Env, key: string): Promise<unknown | null> {
  const object = await env.PICKS.get(key);
  if (!object) return null;
  try { return await object.json(); } catch { return null; }
}

function authorized(request: Request, env: Env): Response | null {
  if (!env.INGEST_TOKEN) return json({ error: "ingest is not configured" }, 503);
  if (request.headers.get("Authorization") !== `Bearer ${env.INGEST_TOKEN}`) {
    return json({ error: "unauthorized" }, 401, { "WWW-Authenticate": "Bearer" });
  }
  return null;
}

async function parseBody(request: Request): Promise<{ body: ArrayBuffer; value: unknown } | Response> {
  const body = await request.arrayBuffer();
  if (body.byteLength === 0) return json({ error: "empty body" }, 400);
  if (body.byteLength > MAX_INGEST_BYTES) return json({ error: "body too large" }, 413);
  try { return { body, value: JSON.parse(new TextDecoder().decode(body)) }; }
  catch { return json({ error: "invalid JSON" }, 400); }
}

async function ingestLatest(request: Request, env: Env): Promise<Response> {
  const authError = authorized(request, env);
  if (authError) return authError;
  const parsed = await parseBody(request);
  if (parsed instanceof Response) return parsed;
  if (!isLatestPicks(parsed.value)) return json({ error: "invalid latest.json shape" }, 400);
  await env.PICKS.put(LATEST_KEY, parsed.body, { httpMetadata: { contentType: "application/json; charset=utf-8" } });
  return json({ ok: true });
}

async function ingestWatchCalendar(request: Request, env: Env): Promise<Response> {
  const authError = authorized(request, env);
  if (authError) return authError;
  const parsed = await parseBody(request);
  if (parsed instanceof Response) return parsed;
  if (!isWatchCalendar(parsed.value)) return json({ error: "invalid watch_calendar.json shape" }, 400);
  // 0.13.0: keep per-model tracks (gpt / claude); drop only the retired llm / multi_hit tracks.
  let body: ArrayBuffer | string = parsed.body;
  const cal = parsed.value as WatchCalendar & Record<string, unknown>;
  if (cal.tracks && (cal.tracks.llm !== undefined || cal.tracks.multi_hit !== undefined)) {
    const { llm: _l, multi_hit: _m, ...keep } = cal.tracks;
    body = JSON.stringify({ ...cal, tracks: keep });
  }
  await env.PICKS.put(WATCH_CALENDAR_KEY, body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
  return json({ ok: true, key: WATCH_CALENDAR_KEY, days: parsed.value.days.length });
}

async function ingestNewsEvents(request: Request, env: Env): Promise<Response> {
  const authError = authorized(request, env);
  if (authError) return authError;
  const parsed = await parseBody(request);
  if (parsed instanceof Response) return parsed;
  if (!isNewsEventsPayload(parsed.value)) return json({ error: "invalid news_events.json shape" }, 400);
  await env.PICKS.put(NEWS_EVENTS_KEY, parsed.body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
  return json({ ok: true, key: NEWS_EVENTS_KEY, events: parsed.value.events.length });
}


async function ingestHeatmap(request: Request, env: Env): Promise<Response> {
  const authError = authorized(request, env);
  if (authError) return authError;
  const parsed = await parseBody(request);
  if (parsed instanceof Response) return parsed;
  if (!isHeatmapPayload(parsed.value)) return json({ error: "invalid heatmap.json shape" }, 400);
  await env.PICKS.put(HEATMAP_KEY, parsed.body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
  const industries = parsed.value.industries.length;
  const stocks = parsed.value.industries.reduce((n, ind) => n + (ind.stocks?.length || 0), 0);
  return json({ ok: true, key: HEATMAP_KEY, industries, stocks, asof: parsed.value.asof });
}

async function renderHeatmap(env: Env): Promise<Response> {
  // Page shell always renders; client loads /api/heatmap.json (allows empty-state UI).
  return html(
    pageShell(
      heatmapView(siteNavigation("heatmap"), WORKER_BUILD),
      HEATMAP_COPY.title + HEATMAP_UI.pageTitleSuffix,
      HEATMAP_COPY.blurb,
    ),
    200,
    PUBLIC_CACHE,
  );
}


async function ingestDetail(request: Request, env: Env, code: string): Promise<Response> {
  const authError = authorized(request, env);
  if (authError) return authError;
  const parsed = await parseBody(request);
  if (parsed instanceof Response) return parsed;
  if (!isStockDetail(parsed.value) || parsed.value.symbol !== code) {
    return json({ error: "invalid detail JSON or symbol mismatch" }, 400);
  }
  await env.PICKS.put(`${DETAIL_PREFIX}${code}.json`, parsed.body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
  return json({ ok: true, symbol: code });
}

async function renderHome(env: Env, url: URL): Promise<Response> {
  const data = await readJson(env, LATEST_KEY);
  if (!data) return html(pageShell(errorState("暂无选股数据", "latest.json 尚未上传。")), 503);
  if (!isLatestPicks(data)) return html(pageShell(errorState("数据格式错误", "latest.json 不符合预期格式。")), 503);
  return html(pageShell(picksView(data, homeView(url.searchParams.get("view")), pickModelKey(url.searchParams.get("model")))), 200, PUBLIC_CACHE);
}

async function renderDetail(env: Env, code: string): Promise<Response> {
  const data = await readJson(env, `${DETAIL_PREFIX}${code}.json`);
  if (!data || !isStockDetail(data)) {
    return html(pageShell(errorState("找不到这只股票", "详情数据尚未生成，或股票代码不存在。"), "找不到这只股票 · 巴小卡股市监控"), 404);
  }
  const displayName = data.name || "暂无";
  return html(pageShell(stockDetailView(data), `${code} ${displayName} · 巴小卡股市监控`, `${code} ${displayName} 股票详情 · 巴小卡股市监控`));
}

async function renderCalendar(env: Env, url: URL): Promise<Response> {
  const data = await readJson(env, WATCH_CALENDAR_KEY);
  if (!data) return html(pageShell(errorState("暂无观察日历数据", "watch_calendar.json 尚未上传。"), "观察日历 · 巴小卡股市监控"), 503);
  if (!isWatchCalendar(data)) return html(pageShell(errorState("数据格式错误", "watch_calendar.json 不符合预期格式。"), "观察日历 · 巴小卡股市监控"), 503);
  return html(pageShell(calendarView(data, pickModelKey(url.searchParams.get("model"))), "观察日历 · 巴小卡股市监控", "每日扫盘 5 只：T 15:05 推荐 → T+1 09:35 开买 → T+2 09:35 开卖结算，预估收益日历。"));
}

async function renderNews(env: Env): Promise<Response> {
  const data = await readJson(env, NEWS_EVENTS_KEY);
  if (!data) return html(pageShell(errorState("暂无热点财经数据", "news_events.json 尚未上传。"), "巴小卡股市监控 · 热点财经"), 503);
  if (!isNewsEventsPayload(data)) return html(pageShell(errorState("数据格式错误", "news_events.json 不符合预期格式。"), "巴小卡股市监控 · 热点财经"), 503);
  return html(pageShell(newsView(data), "巴小卡股市监控 · 热点财经", "小时扫描 · 披露优先。财报、并购、法务以公告为准；舆论可选且非事实。"));
}

function isLatestPicks(value: unknown): value is LatestPicks {
  if (!isRecord(value)) return false;
  return typeof value.generated_at === "string" && typeof value.mode === "string" &&
    (value.names === undefined || (isRecord(value.names) && Object.values(value.names).every((name) => typeof name === "string"))) &&
    (value.quotes === undefined || (isRecord(value.quotes) && Object.values(value.quotes).every(isQuoteSnapshot))) &&
    (value.meta === undefined || (isRecord(value.meta) && Object.values(value.meta).every(isPickMeta))) &&
    Array.isArray(value.strategies) && value.strategies.every((strategy) => isRecord(strategy) &&
      typeof strategy.name === "string" && Array.isArray(strategy.symbols) &&
      strategy.symbols.every((symbol) => typeof symbol === "string"));
}

function isPickMeta(value: unknown): value is PickMeta {
  return isRecord(value) && (typeof value.industry === "string" || value.industry === null) && typeof value.board === "string";
}

function isQuoteSnapshot(value: unknown): value is QuoteSnapshot {
  if (!isRecord(value)) return false;
  return ["close", "chg_pct", "volume", "vol_chg_pct"].every((key) => value[key] === null || finiteNumber(value[key]));
}

function isStockDetail(value: unknown): value is StockDetail {
  if (!isRecord(value)) return false;
  return typeof value.symbol === "string" && /^\d{6}$/.test(value.symbol) &&
    (typeof value.name === "string" || value.name === null) && typeof value.market === "string" &&
    Array.isArray(value.ohlcv_60d) && Array.isArray(value.recent_reports) &&
    Array.isArray(value.picked_strategies) && value.picked_strategies.every((name) => typeof name === "string");
}

function isOptionalDate(value: unknown): boolean {
  return value === undefined || value === null || (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value));
}

function isNullableNumber(value: unknown): boolean {
  return value === null || finiteNumber(value);
}

function isWatchDay(day: unknown): day is WatchDay {
  if (!isRecord(day) || !/^\d{4}-\d{2}-\d{2}$/.test(String(day.date))) return false;
  if (!(isNullableNumber(day.eq_avg_chg_pct) && (day.eq_sum_chg_pct === undefined || isNullableNumber(day.eq_sum_chg_pct)) && (day.cum_eq_avg_chg_pct === undefined || finiteNumber(day.cum_eq_avg_chg_pct)))) return false;
  if (!(day.status === undefined || day.status === "settled" || day.status === "pending" || day.status === "paused")) return false;
  if (!(isOptionalDate(day.buy_date) && isOptionalDate(day.sell_date))) return false;
  if (!Array.isArray(day.stocks)) return false;
  const stocksOk = day.stocks.every((stock) => {
    if (!isRecord(stock) || !/^\d{6}$/.test(String(stock.code)) || typeof stock.name !== "string") return false;
    if (!isNullableNumber(stock.buy_open) || !isNullableNumber(stock.chg_pct)) return false;
    const sell = stock.sell_open !== undefined ? stock.sell_open : stock.sell_close;
    return isNullableNumber(sell);
  });
  if (!stocksOk) return false;
  if (!(day.n === undefined || finiteNumber(day.n))) return false;
  return true;
}

function isWatchTrack(value: unknown): value is WatchTrack {
  if (!isRecord(value)) return false;
  for (const key of ["id", "label", "source", "model", "days_ref"]) {
    if (value[key] !== undefined && typeof value[key] !== "string") return false;
  }
  if (value.days !== undefined && !(Array.isArray(value.days) && value.days.every(isWatchDay))) return false;
  if (value.archived_days !== undefined && !(Array.isArray(value.archived_days) && value.archived_days.every(isWatchDay))) return false;
  return value.days !== undefined || value.days_ref !== undefined;
}

function isWatchCalendar(value: unknown): value is WatchCalendar {
  if (!isRecord(value) || typeof value.generated_at !== "string" || !Array.isArray(value.symbols) || !Array.isArray(value.days)) return false;
  if (value.note !== undefined && typeof value.note !== "string") return false;
  if (value.default_track !== undefined && typeof value.default_track !== "string") return false;
  const symbolsValid = value.symbols.every((symbol) => isRecord(symbol) && /^\d{6}$/.test(String(symbol.code)) && typeof symbol.name === "string");
  const daysValid = value.days.every(isWatchDay);
  if (!(symbolsValid && daysValid)) return false;
  if (value.tracks !== undefined) {
    if (!isRecord(value.tracks)) return false;
    for (const track of Object.values(value.tracks)) {
      if (track === undefined) continue;
      if (!isWatchTrack(track)) return false;
    }
  }
  return true;
}
function isNewsCategory(value: unknown): value is NewsCategory {
  return value === "earnings" || value === "mna" || value === "legal" || value === "opinion";
}

function isNewsEvent(value: unknown): value is NewsEvent {
  if (!isRecord(value)) return false;
  const codeOk = typeof value.code === "string" && (value.code === "" || /^\d{6}$/.test(value.code));
  const precOk = value.time_precision === undefined || value.time_precision === "day" || value.time_precision === "minute";
  return typeof value.id === "string" && value.id.length > 0 &&
    typeof value.datetime === "string" && typeof value.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value.date) &&
    typeof value.company === "string" && codeOk &&
    typeof value.title === "string" && typeof value.summary === "string" &&
    typeof value.source_name === "string" && typeof value.source_url === "string" &&
    isNewsCategory(value.category) && precOk &&
    (value.tags === undefined || (Array.isArray(value.tags) && value.tags.every((t) => typeof t === "string")));
}

function isNewsEventsPayload(value: unknown): value is NewsEventsPayload {
  if (!isRecord(value) || typeof value.generated_at !== "string" || !Array.isArray(value.events)) return false;
  if (value.scanned_at !== undefined && typeof value.scanned_at !== "string") return false;
  if (value.opinion_enabled !== undefined && typeof value.opinion_enabled !== "boolean") return false;
  if (value.note !== undefined && typeof value.note !== "string") return false;
  if (!value.events.every(isNewsEvent)) return false;
  if (value.by_day !== undefined) {
    if (!isRecord(value.by_day)) return false;
    for (const [day, bucket] of Object.entries(value.by_day)) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !isRecord(bucket) || !finiteNumber(bucket.total)) return false;
    }
  }
  return true;
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function calendarView(data: WatchCalendar, model: PickModelKey = "gpt"): string {
  // 0.13.1: server-rendered pool / detail read only the selected model's track.
  // Claude UI paused — always GPT track for SSR pool/detail
  const emptyModel = false;
  const symbols = (data.symbols.length ? data.symbols : WATCH_POOL.map((code) => ({ code, name: code }))).slice(0, 5);
  const emptyText = escapeHtml(emptyBackfillingCopy(MODEL_GPT_NAME));
  const poolData = JSON.stringify(symbols).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
  const strategyTipBadge = "统计预估策略";
  const gptDays = (data.tracks?.gpt?.days && Array.isArray(data.tracks.gpt.days)) ? data.tracks.gpt.days : data.days;
  const lastDate = gptDays.map((d) => d.date).sort().pop() || new Date().toISOString().slice(0, 10);
  const fallbackMonth = lastDate.slice(0, 7);
  return `<style>${MODEL_SWITCH_CSS}
    .calendar-totals{display:flex;flex-direction:column;gap:10px;min-width:0}.bf-note{margin:0;padding:10px 12px;border:1px dashed #3b4270;border-radius:10px;background:rgba(154,168,255,.05);color:#aab3e8;font:400 11px/1.55 "PingFang SC",sans-serif}.bf-note p{margin:0}.bf-note p+p{margin-top:4px}.bf-dot-inline{display:inline-block;width:6px;height:6px;margin:0 6px 1px 0;border-radius:50%;background:#9aa8ff;vertical-align:middle}.bf-dot{position:absolute;top:6px;right:6px;width:6px;height:6px;border-radius:50%;background:#9aa8ff;pointer-events:none}.bf-tag{display:inline-block;margin-left:8px;padding:1px 7px;border:1px dashed #7d88d8;border-radius:999px;color:#b9c1ff;background:rgba(154,168,255,.08);font:600 11px/1.5 "PingFang SC",sans-serif;vertical-align:middle}.bf-tag[hidden],.bf-tip[hidden],.bf-note[hidden]{display:none}.detail-empty{padding:18px 0!important;color:#9aa8ff;font-size:12px;line-height:1.6;text-align:left!important}.bf-tip{margin:0 0 12px;color:#9aa8ff;font-size:12px;line-height:1.55}.daily-average strong{white-space:nowrap}.daily-average.is-paused{flex-direction:column-reverse;align-items:flex-start;gap:8px}.daily-average.is-paused>div>span{display:none}.daily-average.is-paused small{margin-top:0;font-size:11px;line-height:1.55}.daily-average.is-paused strong{font-size:24px}.calendar-day.is-future{border-style:dashed;border-color:#1b2227;background:#0a0d10;opacity:.5;cursor:default}.calendar-day.is-future:hover{transform:none}.kpi-basis{margin-left:6px;color:#6f7a82;font:500 10px/1.2 "PingFang SC",sans-serif;letter-spacing:0}.calendar-kpi .kpi-card-sub{margin-top:6px;color:#8a95c8;font:500 11px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,"PingFang SC",monospace;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.calendar-kpi .kpi-card-sub[hidden]{display:none}.cal-rules{margin:0;min-width:0}.cal-rules-row{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;min-width:0}.cal-rules-text{flex:1 1 auto;min-width:0}.cal-rules-text p{margin:0;color:#8b949c;font:400 12px/1.55 "PingFang SC",sans-serif}.cal-rules-text p+p{margin-top:4px}.cal-help{flex:0 0 auto;width:22px;height:22px;margin-top:1px}.cal-tip{margin:8px 0 0;padding:10px 12px;border:1px dashed #3b4270;border-radius:10px;background:rgba(154,168,255,.05);color:#aab3e8;font:400 11px/1.55 "PingFang SC",sans-serif;max-width:100%;overflow-wrap:anywhere;word-break:break-word}.cal-tip[hidden]{display:none}.cal-tip p{margin:0}.cal-tip p+p{margin-top:6px}.strategy-tip-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.strategy-tip-head .strategy-tip-badge{margin-bottom:0}.strategy-tip-head .cal-help{border-color:#315641;color:var(--accent)}.rerun-block{margin-top:18px;padding-top:14px;border-top:1px dashed #3b4270}.rerun-block[hidden]{display:none}.rerun-title{margin:0 0 8px;color:#b9c1ff;font:650 13px/1.4 "PingFang SC",sans-serif}.rerun-block .daily-average{border-color:#2f3560;background:rgba(154,168,255,.04)}.rerun-block .daily-average strong{font-size:22px}.calendar-day.is-pending.is-paused .day-metric,.cal-paused-text{color:#f0b429}.calendar-day.is-pending.is-paused{border-color:rgba(240,180,41,.35)}
    .calendar-page{--cal-up:#ff4d4f;--cal-down:#3dd68c;--cal-flat:#a1aab2;padding-top:38px}.calendar-page .site-nav{margin-bottom:42px}.calendar-hero{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,.55fr);gap:40px;align-items:stretch;padding-bottom:32px;border-bottom:1px solid var(--line)}.calendar-hero>div:first-child{display:flex;flex-direction:column;justify-content:flex-end}.calendar-hero h1{font-size:clamp(46px,7vw,76px)}.strategy-tip{margin:18px 0 0;padding:14px 16px;border:1px solid #2a3a32;border-radius:10px;background:#0a120e;color:#b7c2bb;font-size:13px;line-height:1.7;min-width:0;max-width:100%}.strategy-tip-badge{display:inline-block;padding:3px 8px;border:1px solid #315641;border-radius:999px;color:var(--accent);font-size:11px}.strategy-tip-flow{margin:0 0 8px;color:#dce3df;font:600 12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere}.strategy-tip-foot{margin:0;color:#7f8a91;font-size:11px}.calendar-page .help-toggle{display:grid;place-items:center;width:22px;height:22px;padding:0;border:1px solid #3b4270;border-radius:50%;color:#b9c1ff;background:transparent;font:700 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}.calendar-page .help-toggle:hover,.calendar-page .help-toggle:focus-visible{border-color:#9aa8ff;outline:none;background:rgba(154,168,255,.08)}.calendar-meta{display:flex;justify-content:space-between;gap:18px;padding:14px 0 24px;color:var(--muted);font-size:12px}.calendar-kpis{display:grid;grid-template-columns:1fr 1fr;gap:10px;align-items:stretch}.calendar-kpi{min-width:0;width:100%;min-height:96px;display:grid;grid-template-rows:auto auto auto;align-content:start;padding:12px 14px;border:1px solid #222930;border-radius:12px;background:linear-gradient(145deg,rgba(19,24,29,.96),rgba(13,16,20,.96))}.calendar-kpi .kpi-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;min-height:18px}.calendar-kpi .kpi-lab{color:#9ba5aa;font:650 11px/1.2 "PingFang SC",sans-serif;letter-spacing:.04em}.calendar-kpi .kpi-sub{color:#59616a;font:500 11px/1.2 "PingFang SC",sans-serif;font-style:normal;text-align:right;white-space:nowrap}.calendar-kpi .kpi-val{margin-top:8px;min-height:32px;font:720 26px/1.1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}.pool-panel{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:18px 20px}.pool-copy h2{margin:0 0 6px}.pool-copy p{margin:0;color:var(--muted);font-size:12px}.pool-list{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px}.pool-chip{display:flex;align-items:baseline;gap:7px;padding:9px 11px;border:1px solid #294138;border-radius:8px;background:#0a100d;font-size:12px}.pool-chip b{color:var(--accent);font:650 12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.03em}.pool-chip span{color:#8f9a9f}.calendar-layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(280px,.72fr);gap:12px;margin-top:12px}.calendar-panel,.day-panel{min-width:0}.calendar-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}.month-actions{display:flex;gap:7px}.month-button{display:grid;place-items:center;width:44px;height:44px;border:1px solid #304039;border-radius:8px;color:#d3dad7;background:#0b100e;font-size:18px;cursor:pointer}.month-button:hover:not(:disabled),.month-button:focus-visible{border-color:var(--accent);color:var(--accent);outline:none}.month-button:disabled{opacity:.3;cursor:not-allowed}.month-title{font:650 20px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;letter-spacing:.02em}.weekdays,.calendar-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:7px}.weekdays{margin-bottom:7px}.weekdays span{padding:4px 0;color:#68737b;font-size:10px;text-align:center}.calendar-grid{min-height:458px}.calendar-blank{min-height:80px}.calendar-day{position:relative;display:flex;min-width:0;min-height:80px;padding:10px;flex-direction:column;align-items:flex-start;justify-content:space-between;border:1px solid #273139;border-radius:9px;color:var(--text);background:#0b0f12;text-align:left;cursor:pointer;font:inherit}.calendar-day:hover:not(:disabled){border-color:#56635d;transform:translateY(-1px)}.calendar-day:focus-visible{outline:2px solid var(--accent);outline-offset:1px}.calendar-day.is-selected{border-color:#d5ded9;box-shadow:inset 0 0 0 1px rgba(255,255,255,.28)}.calendar-day.cal-up{background:color-mix(in srgb,var(--cal-up) var(--heat),#0b0f12);border-color:color-mix(in srgb,var(--cal-up) 42%,#273139)}.calendar-day.cal-down{background:color-mix(in srgb,var(--cal-down) var(--heat),#0b0f12);border-color:color-mix(in srgb,var(--cal-down) 35%,#273139)}.day-number{color:#dce2e4;font:600 12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.day-metric{font:700 13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}.cal-up .day-metric,.cal-up-text{color:var(--cal-up)}.cal-down .day-metric,.cal-down-text{color:var(--cal-down)}.cal-flat .day-metric,.cal-flat-text{color:var(--cal-flat)}.calendar-day.is-closed,.calendar-day.is-pending{border-style:dashed;color:#657078;background:#090d0f}.calendar-day.is-closed{cursor:default}.calendar-day.is-pending{cursor:pointer}.calendar-day.is-closed .day-metric,.calendar-day.is-pending .day-metric{color:#58636a;font-weight:500;font-size:11px}.calendar-loading{grid-column:1/-1;display:grid;place-items:center;min-height:420px;color:var(--muted);font-size:13px}.day-panel{display:flex;flex-direction:column}.day-panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}.day-panel-head h2{margin:0}.selected-date{color:var(--muted);font:11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.daily-average{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;padding:16px;border:1px solid #26342e;border-radius:10px;background:#0a0f0c}.daily-average span{display:block;color:#9ba5aa;font-size:12px}.daily-average small{display:block;margin-top:7px;color:#657068;font-size:10px}.daily-average strong{font:720 28px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}.horizon-meta{display:flex;flex-wrap:wrap;gap:10px 16px;margin-top:12px;color:#7f8a91;font-size:11px}.horizon-meta b{color:#c5cec9;font:600 11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;margin-top:16px}.table-scroll .detail-table{margin-top:0}.detail-table{width:100%;margin-top:16px;border-collapse:collapse;font-size:12px}.detail-table th{padding:0 0 9px;color:#657078;font-size:10px;font-weight:500;text-align:left}.detail-table th:last-child,.detail-table td:last-child{text-align:right}.detail-table th:last-child,.detail-table .stock-return{white-space:nowrap}.detail-table td{padding:13px 0;border-top:1px solid #212a2f}.stock-cell{display:grid;gap:4px}.stock-cell b{font:650 12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.stock-cell span{color:#7f8a91;font-size:11px}.stock-return{font:700 13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}.stock-legs{display:block;margin-top:4px;color:#657068;font:10px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.trend-panel{margin-top:12px}.trend-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:16px}.trend-head h2{margin:0 0 6px}.trend-head p{margin:0;color:var(--muted);font-size:11px}.trend-legend{display:flex;gap:15px;color:#7b858c;font-size:10px}.trend-legend span{display:flex;align-items:center;gap:6px}.trend-legend i{width:7px;height:7px;border-radius:50%;background:var(--cal-up)}.trend-legend span:last-child i{background:var(--cal-down)}.trend-chart{min-height:282px;border:1px solid #202930;border-radius:10px;background:#090d10}.trend-chart svg{display:block;width:100%;height:auto;min-height:280px}.trend-chart text{fill:#69747b;font:10px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.trend-chart .chart-bar{cursor:pointer;transition:opacity .12s}.trend-chart .chart-bar:hover{opacity:1}.trend-empty{display:grid;place-items:center;min-height:280px;color:var(--muted);font-size:13px}.review-banner{margin:0 0 12px;padding:10px 14px;border-radius:10px;border:1px solid #2a3338;background:#0c1014;color:#aeb7bf;font-size:12px;line-height:1.5}.review-panel{margin-top:8px;padding:10px 12px;border-radius:10px;border:1px solid #3a2424;background:rgba(255,77,79,.06)}.review-lab{display:inline-flex;align-items:center;gap:6px;font:650 11px/1 sans-serif;color:#ff8a8a;letter-spacing:.04em;margin-bottom:8px}.review-lab i{width:6px;height:6px;border-radius:50%;background:var(--cal-up);display:inline-block}.review-tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}.review-tag{padding:4px 8px;border-radius:999px;border:1px solid #4a3030;background:#140f0f;color:#e8c4c4;font-size:11px}.review-bul{margin:0;padding-left:16px;color:#c9b0b0;font-size:12px;line-height:1.55}.review-bul li{margin:2px 0}.explain-panel{margin-top:8px;padding:10px 12px;border-radius:10px;border:1px solid #2a3a32;background:rgba(111,227,162,.06)}.explain-panel .explain-lab{display:inline-flex;align-items:center;gap:6px;font:650 11px/1 sans-serif;color:#8fe0b4;letter-spacing:.04em;margin-bottom:6px}.explain-panel .reason-chip{display:inline-block;margin:0 0 6px;padding:3px 8px;border:1px solid #315641;border-radius:999px;color:#b8f0d0;background:rgba(111,227,162,.08);font:650 11px/1.2 "PingFang SC",sans-serif}.explain-panel .explain-body{margin:0;color:#c5cec9;font-size:12px;line-height:1.55}.explain-panel .explain-fallback{color:#8b949c}.detail-table td{vertical-align:top}
    @media(max-width:899px){.calendar-hero{grid-template-columns:1fr;align-items:stretch}.pool-panel{align-items:flex-start;flex-direction:column}.pool-list{justify-content:flex-start}.calendar-layout{grid-template-columns:1fr}.calendar-grid{min-height:0}.day-panel{min-height:0}.trend-chart,.trend-chart svg{width:100%;max-width:100%}.calendar-page .site-nav{max-width:100%}}
    @media(max-width:599px){.model-bar{padding:10px 12px}.bf-dot{top:4px;right:4px}.calendar-page{padding-top:24px}.calendar-page .site-nav{margin-bottom:24px;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;width:100%;scrollbar-width:none}.calendar-page .site-nav::-webkit-scrollbar{display:none}.calendar-hero{gap:18px}.calendar-hero h1{font-size:clamp(36px,11vw,52px)}.calendar-meta{align-items:flex-start;flex-direction:column}.calendar-kpis{width:100%;display:grid;grid-template-columns:1fr 1fr;gap:8px;justify-content:stretch}.calendar-kpi{min-width:0;width:100%;min-height:108px;padding:12px}.calendar-kpi .kpi-sub{white-space:normal}.calendar-kpi .kpi-val{font-size:22px}.cal-tip{margin-top:8px}.month-button{width:44px;height:44px}.pool-list{display:grid;grid-template-columns:1fr 1fr;width:100%}.pool-chip{min-width:0}.weekdays,.calendar-grid{gap:3px}.calendar-day,.calendar-blank{min-height:56px}.calendar-day{padding:5px 3px}.day-number{font-size:11px}.day-metric{font-size:9px}.calendar-day.is-closed .day-metric,.calendar-day.is-pending .day-metric{font-size:8px}.calendar-panel,.day-panel,.trend-panel{padding:14px}.trend-head{align-items:flex-start;flex-direction:column}.trend-legend{display:none}.trend-chart{min-height:220px}.trend-chart svg{min-height:220px}.review-tags{gap:6px}.table-scroll{margin-top:12px}.detail-table{min-width:280px;font-size:12px}}
    @media(max-width:359px){.calendar-kpis{grid-template-columns:1fr}}
  </style><main class="calendar-page">
    ${siteNavigation("calendar", model)}
    <header class="calendar-hero"><div><p class="eyebrow"><span class="pulse" aria-hidden="true"></span>日频推荐 · 开盘结算</p><h1>观察日历</h1></div><div class="calendar-totals"><div class="calendar-kpis" aria-label="月年收益汇总"><div class="calendar-kpi"><div class="kpi-head"><span class="kpi-lab">月收益<span class="kpi-basis">${escapeHtml(LABEL_ACTUAL)}</span></span><em class="kpi-sub" id="month-return-scope">—</em></div><div class="kpi-val" id="month-return">—</div><div class="kpi-card-sub" id="month-card-sub" hidden></div></div><div class="calendar-kpi"><div class="kpi-head"><span class="kpi-lab">年收益<span class="kpi-basis">${escapeHtml(LABEL_ACTUAL)}</span></span><em class="kpi-sub" id="year-return-scope">—</em></div><div class="kpi-val" id="year-return">—</div><div class="kpi-card-sub" id="year-card-sub" hidden></div></div></div><div class="cal-rules" id="cal-rules"><div class="cal-rules-row"><div class="cal-rules-text"><p>${escapeHtml(RULES_LINE1)}</p><p>${escapeHtml(RULES_LINE2)}</p></div><button type="button" class="help-toggle cal-help" aria-label="说明" aria-expanded="false" aria-controls="cal-rules-tip">?</button></div><div class="cal-tip" id="cal-rules-tip" hidden><p>${escapeHtml(TIP_TWO_TOTALS)}</p><p>${escapeHtml(TIP_BACKFILL_LEGEND)}</p><p id="cal-kpi-track-tip" hidden></p></div></div></div></header>
    ${headerModelSubMarkup()}
    <aside class="strategy-tip"><div class="strategy-tip-head"><div class="strategy-tip-badge">${escapeHtml(strategyTipBadge)}</div><button type="button" class="help-toggle cal-help" aria-label="说明" aria-expanded="false" aria-controls="strategy-tip-panel">?</button></div><p class="strategy-tip-flow">${escapeHtml(STRATEGY_TIMELINE)}</p><p class="strategy-tip-foot">${escapeHtml(STRATEGY_DISCLAIMER)}</p><div class="cal-tip" id="strategy-tip-panel" hidden><p>${escapeHtml(TIP_STRATEGY)}</p></div>
    </aside>
    <div class="calendar-meta"><span>更新于 ${escapeHtml(formatShanghaiTime(data.generated_at))}</span><span>红涨 <b class="cal-up-text">#ff4d4f</b> · 绿跌 <b class="cal-down-text">#3dd68c</b> · 未结算灰色</span></div>
    <section class="panel pool-panel"><div class="pool-copy"><h2>最新信号日推荐</h2><p>当日 5 只（随扫盘更新）</p></div><div class="pool-list" id="pool-list">${emptyModel ? emptyText : symbols.map((symbol) => `<span class="pool-chip"><b>${escapeHtml(symbol.code)}</b><span>${escapeHtml(symbol.name)}</span></span>`).join("")}</div></section>
    <div class="calendar-layout">
      <section class="panel calendar-panel"><header class="calendar-toolbar"><h2 class="month-title" id="month-title">—</h2><div class="month-actions"><button class="month-button" id="prev-month" type="button" aria-label="上个月">‹</button><button class="month-button" id="next-month" type="button" aria-label="下个月">›</button></div></header><div class="weekdays" aria-hidden="true"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div><div class="calendar-grid" id="calendar-grid" role="grid" aria-labelledby="month-title"><div class="calendar-loading">正在读取观察日历…</div></div></section>
      <aside class="panel day-panel"><header class="day-panel-head"><h2>当日明细<span class="bf-tag" id="bf-tag" hidden>回溯</span></h2><span class="selected-date">信号日 <time id="selected-date">—</time></span></header><p class="bf-tip" id="bf-tip" hidden>${escapeHtml(TIP_BACKFILL)}</p><div class="daily-average"><div><span>预估收益（涨跌幅合计）</span><small id="avg-caption">五只涨跌幅相加 · 次日开 → 再下一日开</small></div><strong id="daily-average">—</strong></div><div class="horizon-meta" id="horizon-meta"><span>买入开盘 <b id="buy-date">—</b></span><span>卖出开盘 <b id="sell-date">—</b></span></div><p class="review-banner" id="review-banner">下跌复盘按规则因子自动生成，仅供观察，不构成投资建议。</p><div class="table-scroll"><table class="detail-table"><thead><tr><th>观察池</th><th>收益（%）</th></tr></thead><tbody id="detail-body">${emptyModel ? `<tr><td class="detail-empty" colspan="2">${emptyText}</td></tr>` : symbols.map((symbol) => `<tr><td><span class="stock-cell"><b>${escapeHtml(symbol.code)}</b><span>${escapeHtml(symbol.name)}</span></span></td><td class="stock-return">—</td></tr>`).join("")}</tbody></table></div><section class="rerun-block" id="rerun-block" hidden aria-label="${escapeHtml(LABEL_RERUN)}"><h3 class="rerun-title">${escapeHtml(DETAIL_RERUN_TITLE)}</h3><p class="bf-tip" id="rerun-tip">${escapeHtml(TIP_BACKFILL)}</p><div class="daily-average"><div><span>预估收益（涨跌幅合计）</span><small id="rerun-caption">—</small></div><strong id="rerun-average">—</strong></div><div class="horizon-meta"><span>买入开盘 <b id="rerun-buy">—</b></span><span>卖出开盘 <b id="rerun-sell">—</b></span></div><div class="table-scroll"><table class="detail-table"><thead><tr><th>观察池</th><th>收益（%）</th></tr></thead><tbody id="rerun-body"></tbody></table></div></section></aside>
    </div>
    <section class="panel trend-panel"><header class="trend-head"><div><h2>预估收益趋势</h2><p>涨跌幅合计（%）</p></div><div class="trend-legend" aria-hidden="true"><span><i></i>上涨</span><span><i></i>下跌</span></div></header><div class="trend-chart" id="trend-chart"><div class="trend-empty">正在读取趋势…</div></div></section>
    ${footer()}
  </main><script>(()=>{
    let pool=${poolData};
    const grid=document.getElementById("calendar-grid"),monthTitle=document.getElementById("month-title"),prev=document.getElementById("prev-month"),next=document.getElementById("next-month"),selectedDate=document.getElementById("selected-date"),dailyAverage=document.getElementById("daily-average"),avgCaption=document.getElementById("avg-caption"),buyDateEl=document.getElementById("buy-date"),sellDateEl=document.getElementById("sell-date"),detailBody=document.getElementById("detail-body"),trend=document.getElementById("trend-chart"),poolList=document.getElementById("pool-list");
    let days=[],byDate=new Map(),months=[],month="",selected="";
    ${modelSwitchScript()}
    const MODEL_LABELS={gpt:"GPT-6.1 Sol",claude:"Claude Opus 5.5"},HEADER_MODEL_SUB=${JSON.stringify(HEADER_MODEL_SUB)},HEADER_MODEL_SUB_NO_BACKFILL=${JSON.stringify(HEADER_MODEL_SUB_NO_BACKFILL)},MODEL_GPT_NAME=${JSON.stringify(MODEL_GPT_NAME)},FALLBACK_MONTH="${fallbackMonth}";let model="gpt",trackDays={gpt:[],claude:[]},kpiBySource=null,loaded=false;
    const modelSub=document.getElementById("model-sub"),bfTag=document.getElementById("bf-tag"),bfTip=document.getElementById("bf-tip");
    (function(){const buttons=[...document.querySelectorAll(".calendar-page .help-toggle")];for(const button of buttons){button.addEventListener("click",()=>{const opening=button.getAttribute("aria-expanded")!=="true";for(const other of buttons){const panel=document.getElementById(other.getAttribute("aria-controls")||"");other.setAttribute("aria-expanded","false");other.setAttribute("aria-label","说明");if(panel)panel.hidden=true}if(opening){const panel=document.getElementById(button.getAttribute("aria-controls")||"");button.setAttribute("aria-expanded","true");button.setAttribute("aria-label","收起说明");if(panel)panel.hidden=false}})} })();

    function isBackfill(day){return !!day&&(day.backfill===true||day.actual_basis==="backfill")}function hasLive(day){return !!day&&!!day.live&&typeof day.live==="object"&&day.actual_basis!=="backfill"}function actualDay(day){if(!hasLive(day))return day;return Object.assign({},day.live,{date:day.date,backfill:false})}function rerunOf(day){return hasLive(day)&&isBackfill(day)?day:null}const CARD_SUB=${JSON.stringify(CARD_SUB)},CARD_SUB_NO_BACKFILL=${JSON.stringify(CARD_SUB_NO_BACKFILL)};const TIP_BACKFILL=${JSON.stringify(TIP_BACKFILL)},TIP_BACKFILL_EARLY=${JSON.stringify(TIP_BACKFILL_EARLY)};const MARKET_HOLIDAYS=new Set(${JSON.stringify(MARKET_HOLIDAYS_2026)});function cstToday(){return new Date(Date.now()+8*3600*1000).toISOString().slice(0,10)}function isTradingDate(date){const wd=new Date(date+"T00:00:00Z").getUTCDay();return wd!==0&&wd!==6&&!MARKET_HOLIDAYS.has(date)}function tipFor(day){return day&&day.basis_verified===false?TIP_BACKFILL_EARLY:TIP_BACKFILL}
    function emptyCopy(){return MODEL_LABELS[model]+" 的历史数据还在补算，稍后再来看。"}
    function setModel(k){model="gpt";sxSyncModelUi(model);days=trackDays.gpt||[];if(loaded)applyDays()}
        function dayMetric(day){if(!day)return null;if(Number.isFinite(day.eq_sum_chg_pct))return day.eq_sum_chg_pct;const stocks=Array.isArray(day.stocks)?day.stocks:[];const vals=stocks.map((s)=>s&&s.chg_pct).filter((v)=>Number.isFinite(v));if(vals.length)return vals.reduce((a,b)=>a+b,0);if(Number.isFinite(day.eq_avg_chg_pct)&&Number.isFinite(day.n)&&day.n>0)return day.eq_avg_chg_pct*day.n;return Number.isFinite(day.eq_avg_chg_pct)?day.eq_avg_chg_pct:null}function isPaused(day){return !!day&&(day.status==="paused"||day.pick_status==="paused")}function isPending(day){const m=dayMetric(day);return !day||day.status==="pending"||m===null||m===undefined||!Number.isFinite(m)}
    function comparableDay(day){if(!day)return false;if(isPaused(day))return false;if(day.exclude_from_totals===true)return false;if(day.status!=="settled")return false;const n=(day.n!=null)?day.n:((day.stocks&&day.stocks.length)||0);if(n!==5)return false;const m=dayMetric(day);return Number.isFinite(m)}
    function applyDays(){if(!days.length){renderEmptyModel();return}byDate=new Map(days.map((day)=>[day.date,day]));const monthSet=new Set(days.map((day)=>day.date.slice(0,7)));months=[...monthSet].sort();if(!months.includes(month))month=months.length?months[months.length-1]:"";if(!byDate.has(selected)){const cur=days.filter((day)=>day.date.slice(0,7)===month);selected=cur.length?cur[cur.length-1].date:(days.length?days[days.length-1].date:"")}const lastWithStocks=[...days].reverse().find((d)=>d&&Array.isArray(d.stocks)&&d.stocks.length);const lastDay=days.length?days[days.length-1]:null;if(isPaused(lastDay)){pool=[];if(poolList){poolList.textContent=isBackfill(lastDay)?pausedBodyBackfill(lastDay.date):"信号日 "+lastDay.date+" · 当天暂停推荐，下一个交易日开盘不买入"}}else if(lastWithStocks){pool=lastWithStocks.stocks.map((s)=>({code:s.code,name:s.name||s.code}));if(poolList){poolList.innerHTML=pool.map((symbol)=>'<span class="pool-chip"><b>'+symbol.code+'</b><span>'+(symbol.name||"")+'</span></span>').join("")}}render()}
    function renderEmptyModel(){byDate=new Map();months=[];selected="";const text=emptyCopy();const parts=FALLBACK_MONTH.split("-");monthTitle.textContent=parts[0]+" 年 "+parts[1]+" 月";grid.innerHTML='<div class="calendar-loading"></div>';grid.firstChild.textContent=text;trend.innerHTML='<div class="trend-empty"></div>';trend.firstChild.textContent=text;pool=[];renderDetail(null);if(poolList)poolList.textContent=text;for(const id of ["month-return","year-return"]){const el=document.getElementById(id);if(el){el.textContent="—";el.className="kpi-val"}}const ms=document.getElementById("month-return-scope"),ys=document.getElementById("year-return-scope");if(ms)ms.textContent=FALLBACK_MONTH;if(ys)ys.textContent=FALLBACK_MONTH.slice(0,4);for(const id of ["month-card-sub","year-card-sub"]){const el=document.getElementById(id);if(el){el.hidden=true;el.textContent=""}}if(modelSub){modelSub.textContent=text;modelSub.classList.add("is-empty")}prev.disabled=true;next.disabled=true}
    function cleanDays(list){return (Array.isArray(list)?list:[]).filter((day)=>day&&/^\\d{4}-\\d{2}-\\d{2}$/.test(day.date)).sort((a,b)=>a.date.localeCompare(b.date))}
    fetch("/api/watch_calendar.json",{headers:{Accept:"application/json"}}).then((response)=>{if(!response.ok)throw new Error("HTTP "+response.status);return response.json()}).then((data)=>{
      if(!data||!Array.isArray(data.days))throw new Error("invalid data");
      const tracks=(data.tracks&&typeof data.tracks==="object")?data.tracks:{},g=tracks.gpt,c=tracks.claude;
      trackDays={gpt:cleanDays(g&&Array.isArray(g.days)?g.days:data.days),claude:cleanDays(c&&Array.isArray(c.days)?c.days:[])};
      kpiBySource=(data.kpi_by_source&&typeof data.kpi_by_source==="object")?data.kpi_by_source:null;
      loaded=true;setModel(sxReadModel());
    }).catch(()=>{grid.innerHTML='<div class="calendar-loading">日历数据读取失败，请稍后重试。</div>';trend.innerHTML='<div class="trend-empty">—</div>'});
    prev.addEventListener("click",()=>move(-1));next.addEventListener("click",()=>move(1));
    function move(delta){const index=months.indexOf(month),target=months[index+delta];if(!target)return;month=target;const current=days.filter((day)=>day.date.slice(0,7)===month);selected=current.length?current[current.length-1].date:"";render()}
    function render(){renderCalendar();renderDetail(byDate.get(selected));renderChart();renderReturns();renderModelSub();const index=months.indexOf(month);prev.disabled=index<=0;next.disabled=index<0||index>=months.length-1}
    function renderCalendar(){const parts=month.split("-").map(Number),year=parts[0],monthNumber=parts[1],count=new Date(Date.UTC(year,monthNumber,0)).getUTCDate(),offset=(new Date(Date.UTC(year,monthNumber-1,1)).getUTCDay()+6)%7;monthTitle.textContent=year+" 年 "+String(monthNumber).padStart(2,"0")+" 月";grid.replaceChildren();for(let i=0;i<offset;i++){const blank=document.createElement("span");blank.className="calendar-blank";blank.setAttribute("aria-hidden","true");grid.append(blank)}for(let number=1;number<=count;number++){const date=month+"-"+String(number).padStart(2,"0"),day=actualDay(byDate.get(date)),button=document.createElement("button"),dayNumber=document.createElement("span"),metric=document.createElement("span");button.type="button";button.className="calendar-day";button.setAttribute("role","gridcell");dayNumber.className="day-number";dayNumber.textContent=String(number);metric.className="day-metric";if(day){if(isPending(day)){button.classList.add("is-pending");if(isPaused(day))button.classList.add("is-paused");metric.textContent=isPaused(day)?"暂停":"未结算";button.setAttribute("aria-label",date+" "+metric.textContent);button.addEventListener("click",()=>{selected=date;render()})}else{const value=dayMetric(day);button.classList.add(value>0?"cal-up":value<0?"cal-down":"cal-flat");button.style.setProperty("--heat",String(Math.round((8+Math.min(Math.abs(value)/50,1)*20)))+"%");metric.textContent=pct(value);button.setAttribute("aria-label",date+" 预估收益 "+pct(value));button.addEventListener("click",()=>{selected=date;render()})} }else if(date>=cstToday()&&isTradingDate(date)){button.classList.add("is-future");button.disabled=true;metric.textContent="";button.setAttribute("aria-label",date+" 未到")}else{button.classList.add("is-closed");button.disabled=true;metric.textContent="休市";button.setAttribute("aria-label",date+" 休市")}if(date===selected)button.classList.add("is-selected");button.append(dayNumber,metric);if(day&&isBackfill(day)){const dot=document.createElement("i");dot.className="bf-dot";dot.setAttribute("aria-hidden","true");button.append(dot);button.setAttribute("aria-label",(button.getAttribute("aria-label")||date)+" · 回溯")}grid.append(button)}}
    const DETAIL_PAUSED_BODY_BACKFILL=${JSON.stringify(DETAIL_PAUSED_BODY_BACKFILL)};function pausedBodyBackfill(date){return DETAIL_PAUSED_BODY_BACKFILL.replace("{date}",date)}
    function renderDetail(rawDay){const day=actualDay(rawDay);renderRerun(rerunOf(rawDay));if(bfTag)bfTag.hidden=!isBackfill(day);if(bfTip){bfTip.hidden=!isBackfill(day);bfTip.textContent=tipFor(day)}if(dailyAverage.parentElement)dailyAverage.parentElement.classList.toggle("is-paused",!!day&&isPaused(day));selectedDate.textContent=day?day.date:"—";buyDateEl.textContent=day&&day.buy_date?day.buy_date:"—";sellDateEl.textContent=day&&day.sell_date?day.sell_date:"—";if(!day){dailyAverage.textContent="—";dailyAverage.className="";avgCaption.textContent=days.length?"五只涨跌幅相加 · 次日开 → 再下一日开":emptyCopy();}else if(isPaused(day)){dailyAverage.textContent="暂停推荐";dailyAverage.className="cal-paused-text";avgCaption.textContent=isBackfill(day)?pausedBodyBackfill(day.date):day.date+" 的选股没有正常完成，当天不给推荐，下一个交易日开盘不买入，这一天也不计入收益合计。";}else if(isPending(day)){dailyAverage.textContent="未结算";dailyAverage.className="cal-flat-text";avgCaption.textContent="持仓尚未走完，暂不计入收益";}else{const m=dayMetric(day);dailyAverage.textContent=pct(m);dailyAverage.className=textClass(m);avgCaption.textContent="五只涨跌幅相加 · 次日开 → 再下一日开 · n="+((day.n!=null)?day.n:(day.stocks||[]).length);}detailBody.replaceChildren();if(!day&&!days.length){const tr=document.createElement("tr"),td=document.createElement("td");td.className="detail-empty";td.colSpan=2;td.textContent=emptyCopy();tr.append(td);detailBody.append(tr);return}const rows=(day&&Array.isArray(day.stocks)&&day.stocks.length)?day.stocks:isPaused(day)?[]:pool.map((symbol)=>({code:symbol.code,name:symbol.name,buy_open:null,sell_open:null,chg_pct:null}));fillRows(detailBody,day,rows)}function fillRows(body,day,rows){for(const stock of rows){const row=document.createElement("tr"),left=document.createElement("td"),right=document.createElement("td"),cell=document.createElement("span"),code=document.createElement("b"),name=document.createElement("span"),legs=document.createElement("span");cell.className="stock-cell";code.textContent=stock.code;name.textContent=stock.name||"";cell.append(code,name);const sell=stock.sell_open!=null?stock.sell_open:stock.sell_close;if(stock&&(stock.buy_open!=null||sell!=null)){legs.className="stock-legs";legs.textContent=price(stock.buy_open)+" → "+price(sell);cell.append(legs)}const exp=(stock&&typeof stock.explain==="string")?stock.explain.trim():"";const rsn=(stock&&typeof stock.reason==="string")?stock.reason.trim():"";const expPanel=document.createElement("div");expPanel.className="explain-panel";const expLab=document.createElement("div");expLab.className="explain-lab";expLab.textContent="推荐理由";expPanel.append(expLab);if(rsn&&exp){const chip=document.createElement("span");chip.className="reason-chip";chip.textContent=rsn;expPanel.append(chip);const body=document.createElement("p");body.className="explain-body";body.textContent=exp;expPanel.append(body)}else{const body=document.createElement("p");body.className="explain-body explain-fallback";body.textContent="规则排序、暂无解释";expPanel.append(body)}left.append(cell);left.append(expPanel);if(!day||isPending(day)){right.className="stock-return cal-flat-text";right.textContent=stock&&Number.isFinite(stock.chg_pct)?pct(stock.chg_pct):"未结算"}else if(stock&&Number.isFinite(stock.chg_pct)){right.className="stock-return "+textClass(stock.chg_pct);right.textContent=pct(stock.chg_pct);if(stock.chg_pct<0&&stock.review&&Array.isArray(stock.review.tags)&&stock.review.tags.length){const panel=document.createElement("div");panel.className="review-panel";const lab=document.createElement("div");lab.className="review-lab";lab.innerHTML="<i></i>下跌复盘";panel.append(lab);const tags=document.createElement("div");tags.className="review-tags";for(const tag of stock.review.tags.slice(0,3)){const span=document.createElement("span");span.className="review-tag";span.textContent=String(tag);tags.append(span)}panel.append(tags);const reasons=Array.isArray(stock.review.reasons)?stock.review.reasons.slice(0,2):[];if(reasons.length){const ul=document.createElement("ul");ul.className="review-bul";for(const line of reasons){const li=document.createElement("li");li.textContent=String(line);ul.append(li)}panel.append(ul)}left.append(panel)}}else{right.className="stock-return cal-flat-text";right.textContent="—"}row.append(left,right);body.append(row)}}function renderRerun(rd){const blk=document.getElementById("rerun-block");if(!blk)return;if(!rd){blk.hidden=true;return}blk.hidden=false;const rt=document.getElementById("rerun-tip");if(rt)rt.textContent=tipFor(rd);const avg=document.getElementById("rerun-average"),cap=document.getElementById("rerun-caption"),body=document.getElementById("rerun-body");if(avg.parentElement)avg.parentElement.classList.toggle("is-paused",isPaused(rd));document.getElementById("rerun-buy").textContent=rd.buy_date||"—";document.getElementById("rerun-sell").textContent=rd.sell_date||"—";if(isPaused(rd)){avg.textContent="暂停推荐";avg.className="cal-paused-text";cap.textContent=pausedBodyBackfill(rd.date)}else if(isPending(rd)){avg.textContent="未结算";avg.className="cal-flat-text";cap.textContent="持仓尚未走完，暂不计入收益"}else{const m=dayMetric(rd);avg.textContent=pct(m);avg.className=textClass(m);cap.textContent="五只涨跌幅相加 · 次日开 → 再下一日开 · n="+((rd.n!=null)?rd.n:(rd.stocks||[]).length)}body.replaceChildren();fillRows(body,rd,Array.isArray(rd.stocks)?rd.stocks:[])}
    function renderChart(){const series=days.map(actualDay).filter((day)=>{if(day.date.slice(0,7)!==month)return false;return comparableDay(day)});if(!series.length){trend.innerHTML='<div class="trend-empty">当月暂无已结算数据</div>';return}const width=900,height=280,left=58,right=22,top=24,bottom=44,plotW=width-left-right,plotH=height-top-bottom,values=series.map((day)=>dayMetric(day)),rawMin=Math.min(0,...values),rawMax=Math.max(0,...values),spread=Math.max(rawMax-rawMin,1),min=rawMin-spread*.12,max=rawMax+spread*.12,slot=plotW/series.length,barW=Math.max(4,Math.min(28,slot*.62)),x=(index)=>left+slot*index+slot/2,y=(value)=>top+(max-value)*plotH/(max-min),y0=y(0);let svg='<svg viewBox="0 0 '+width+' '+height+'" role="img" aria-label="'+month+' 预估收益趋势">';for(let index=0;index<5;index++){const value=max-(max-min)*index/4,py=y(value);svg+='<line x1="'+left+'" y1="'+py+'" x2="'+(width-right)+'" y2="'+py+'" stroke="'+(Math.abs(value)<.0001?'#46534d':'#202a2f')+'" stroke-width="1"/><text x="'+(left-9)+'" y="'+(py+3)+'" text-anchor="end">'+value.toFixed(1)+'</text>'}svg+='<line x1="'+left+'" y1="'+y0+'" x2="'+(width-right)+'" y2="'+y0+'" stroke="#46534d" stroke-width="1.2"/>';const tickIndexes=[0,Math.floor((series.length-1)/4),Math.floor((series.length-1)/2),Math.floor((series.length-1)*3/4),series.length-1].filter((value,index,list)=>list.indexOf(value)===index);for(const index of tickIndexes){svg+='<text x="'+x(index)+'" y="'+(height-16)+'" text-anchor="middle">'+series[index].date.slice(5).replace("-","/")+'</text>'}for(let index=0;index<series.length;index++){const day=series[index],value=dayMetric(day),color=value>0?'#ff4d4f':value<0?'#3dd68c':'#a1aab2',cy=y(value),barTop=Math.min(cy,y0),barH=Math.max(2,Math.abs(cy-y0)),cx=x(index)-barW/2,isSel=day.date===selected,stroke=isSel?'#ffffff':'none',sw=isSel?'2':'0',opacity=isSel?'1':'.9';svg+='<rect class="chart-bar" data-date="'+day.date+'" x="'+cx+'" y="'+barTop+'" width="'+barW+'" height="'+barH+'" rx="2" fill="'+color+'" stroke="'+stroke+'" stroke-width="'+sw+'" opacity="'+opacity+'" style="cursor:pointer"><title>'+day.date+' '+pct(value)+'</title></rect>'}svg+='</svg>';trend.innerHTML=svg;for(const bar of trend.querySelectorAll(".chart-bar")){bar.addEventListener("click",()=>{selected=bar.getAttribute("data-date")||selected;render()})}}
    function horizonSum(prefix,basis){let sum=0,n=0;if(!prefix)return{sum,n};for(const raw of days){if(!String(raw.date||"").startsWith(prefix))continue;const day=basis==="rerun"?raw:actualDay(raw);if(!comparableDay(day))continue;const m=dayMetric(day);if(!Number.isFinite(m))continue;sum+=m;n+=1}return{sum,n}}function backfillDays(prefix){let nb=0;if(!prefix)return 0;for(const raw of days){const day=actualDay(raw);if(String(day.date||"").startsWith(prefix)&&isBackfill(day)&&!isPaused(day)&&day.exclude_from_totals!==true&&(comparableDay(day)||isPending(day)))nb+=1}return nb}function fillCardSub(el,nb,rerun){if(!el)return;if(!rerun.n){el.hidden=true;el.textContent="";return}el.hidden=false;el.textContent=nb?CARD_SUB.replace("{n}",String(nb)).replace("{pct}",pct(rerun.sum)):CARD_SUB_NO_BACKFILL.replace("{pct}",pct(rerun.sum))}function fillKpiTrackTip(){const el=document.getElementById("cal-kpi-track-tip");if(el){el.hidden=true;el.textContent=""}}function renderReturns(){const viewMonth=month||"",viewYear=viewMonth.slice(0,4),mEl=document.getElementById("month-return"),yEl=document.getElementById("year-return"),mScope=document.getElementById("month-return-scope"),yScope=document.getElementById("year-return-scope"),m=horizonSum(viewMonth),y=horizonSum(viewYear),mr=horizonSum(viewMonth,"rerun"),yr=horizonSum(viewYear,"rerun"),mrEl=document.getElementById("month-card-sub"),yrEl=document.getElementById("year-card-sub");fillCardSub(mrEl,backfillDays(viewMonth),mr);fillCardSub(yrEl,backfillDays(viewYear),yr);if(mScope)mScope.textContent=(viewMonth||"—");if(yScope)yScope.textContent=(viewYear||"—");if(mEl){if(!m.n){mEl.textContent="—";mEl.className="kpi-val"}else{mEl.textContent=pct(m.sum);mEl.className="kpi-val "+textClass(m.sum)}}if(yEl){if(!y.n){yEl.textContent="—";yEl.className="kpi-val"}else{yEl.textContent=pct(y.sum);yEl.className="kpi-val "+textClass(y.sum)}}fillKpiTrackTip()}
    function renderModelSub(){if(!modelSub)return;modelSub.classList.remove("is-empty");const mNum=Number((month||FALLBACK_MONTH).slice(5,7)),m=horizonSum(month);let nb=0;for(const raw of days){const day=actualDay(raw);if(String(day.date||"").startsWith(month)&&isBackfill(day)&&!isPaused(day)&&day.exclude_from_totals!==true&&(comparableDay(day)||isPending(day)))nb+=1}const val=m.n?pct(m.sum):"—";modelSub.textContent=nb?HEADER_MODEL_SUB.replace("{name}",MODEL_GPT_NAME).replace("{m}",String(mNum)).replace("{pct}",val).replace("{n}",String(nb)):HEADER_MODEL_SUB_NO_BACKFILL.replace("{name}",MODEL_GPT_NAME).replace("{m}",String(mNum)).replace("{pct}",val)}
function pct(value){if(!Number.isFinite(value))return "—";return (value>0?"+":value<0?"−":"")+Math.abs(value).toFixed(2)+"%"}
    function price(value){if(!Number.isFinite(value))return "—";return Number(value).toFixed(2)}
    function textClass(value){return value>0?"cal-up-text":value<0?"cal-down-text":"cal-flat-text"}
  })()</script>`;
}

function newsView(data: NewsEventsPayload): string {
  const payload = JSON.stringify({
    generated_at: data.generated_at,
    scanned_at: data.scanned_at || data.generated_at,
    opinion_enabled: Boolean(data.opinion_enabled),
    events: data.events,
    by_day: data.by_day || {},
    counts: data.counts || {},
  }).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
  const total = Array.isArray(data.events) ? data.events.length : 0;
  return `<style>
    .news-page{--c-earn:#6fe3a2;--c-mna:#7eb6ff;--c-legal:#ffb86b;--c-social:#c9a0ff;padding-top:38px}
    .news-page .site-nav{margin-bottom:28px}
    .news-top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:14px}
    .news-top h1{margin:0;font-size:clamp(28px,5vw,42px);letter-spacing:-.03em}
    .news-nav-right{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
    .news-btn{min-height:44px;height:44px;padding:0 14px;border-radius:8px;border:1px solid #315641;background:transparent;color:var(--accent);font:650 13px "PingFang SC",sans-serif;cursor:pointer}
    .news-btn:disabled{opacity:.35;cursor:not-allowed}
    .news-ym{font:650 18px ui-monospace,Menlo,monospace;margin:0 4px}
    .news-lede{margin:0 0 12px;color:var(--muted);font-size:13px;line-height:1.5;max-width:720px}
    .news-meta{display:flex;flex-wrap:wrap;gap:10px 16px;margin:0 0 16px;color:var(--muted);font-size:12px;align-items:center}
    .news-meta .live{display:inline-flex;align-items:center;gap:6px;color:var(--accent);font-weight:650}
    .news-meta .live i{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px rgba(111,227,162,.18)}
    .news-meta .stale{color:#ffb86b}
    .filters{display:flex;flex-wrap:wrap;gap:8px}
    .chip{height:28px;padding:0 10px;border-radius:999px;border:1px solid var(--line);background:#0c0f12;color:#c9d0d6;font:650 11px/28px "PingFang SC",sans-serif;cursor:pointer}
    .chip.on{border-color:#3d5a4a;background:rgba(111,227,162,.08);color:var(--accent)}
    .chip.dim{opacity:.45;cursor:not-allowed}
    .news-card{border:1px solid var(--line);border-radius:14px;background:linear-gradient(145deg,rgba(19,24,29,.94),rgba(13,16,20,.94));padding:16px;margin-bottom:14px}
    .news-card h2{margin:0 0 12px;font-size:14px;font-weight:650;color:#c9d0d6;letter-spacing:.03em;display:flex;justify-content:space-between;align-items:center;gap:8px}
    .news-card h2 .sub{color:var(--muted);font-weight:500;font-size:11px}
    .ncal{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
    .nwd{text-align:center;color:#59616a;font-size:11px;padding:4px 0;letter-spacing:.06em}
    .ncell{min-height:72px;border:1px solid #1a2228;border-radius:10px;padding:8px;background:#0b0e11;display:flex;flex-direction:column;gap:6px;cursor:pointer;color:inherit;font:inherit;text-align:left}
    .ncell.empty{background:transparent;border-color:transparent;cursor:default}
    .ncell.out{opacity:.28}
    .ncell.sel{border-color:#3d5a4a;box-shadow:inset 0 0 0 1px rgba(111,227,162,.25)}
    .ncell .d{font:650 12px ui-monospace,Menlo,monospace;color:#aeb7bf}
    .dots{display:flex;flex-wrap:wrap;gap:4px;margin-top:auto}
    .dot{width:8px;height:8px;border-radius:50%}
    .dot.earn{background:var(--c-earn)}.dot.mna{background:var(--c-mna)}.dot.legal{background:var(--c-legal)}.dot.social{background:var(--c-social);opacity:.55}
    .ncnt{font:650 11px ui-monospace,Menlo,monospace;color:#aeb7bf}
    .legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;color:var(--muted);font-size:11px;align-items:center}
    .legend span{display:inline-flex;align-items:center;gap:5px}
    .tl{display:flex;flex-direction:column;gap:0}
    .item{display:grid;grid-template-columns:88px 1fr;gap:14px;padding:16px 0;border-top:1px solid var(--line)}
    .item:first-child{border-top:0;padding-top:4px}
    .when{font:650 12px ui-monospace,Menlo,monospace;color:#aeb7bf;line-height:1.4}
    .when .day{color:var(--muted);font-weight:500;font-size:11px}
    .body{min-width:0}
    .tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;align-items:center}
    .tag{padding:3px 8px;border-radius:999px;font:650 11px/1.2 "PingFang SC",sans-serif;border:1px solid transparent}
    .tag.earn{color:#b8f0d0;border-color:#2a4a38;background:rgba(111,227,162,.08)}
    .tag.mna{color:#c5dcff;border-color:#2a3f5a;background:rgba(126,182,255,.08)}
    .tag.legal{color:#ffd7a8;border-color:#4a3a28;background:rgba(255,184,107,.08)}
    .tag.social{color:#e2d0ff;border-color:#3a2f4a;background:rgba(201,160,255,.08);opacity:.85}
    .tag.warn{color:#ffb0b0;border-color:#4a3030;background:rgba(255,77,79,.06);font-weight:500}
    .code{font:650 12px ui-monospace,Menlo,monospace;color:var(--accent);padding:3px 7px;border-radius:6px;border:1px solid #315641;background:rgba(111,227,162,.05)}
    .code.empty{color:var(--muted);border-color:var(--line);background:transparent}
    .co{color:var(--muted);font-size:12px}
    .title{margin:0 0 6px;font:650 15px/1.35 "PingFang SC",sans-serif;color:#f0f3f5}
    .sum{margin:0 0 10px;color:#aeb7bf;font-size:13px;line-height:1.55}
    .src{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;font-size:12px;color:var(--muted)}
    .src a{color:var(--accent);border-bottom:1px dashed #315641;text-decoration:none}
    .src .site{font-weight:650;color:#c9d0d6}
    .empty-hint{padding:28px 12px;text-align:center;color:#59616a;font-size:13px;border:1px dashed #1a2228;border-radius:10px}
    .news-foot{padding:10px 0 0;color:#59616a;font-size:11px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
    @media(max-width:899px){.news-top{flex-direction:column;align-items:flex-start;gap:14px}.news-card{max-width:100%}.ncal{width:100%}}@media(max-width:599px){.news-page{padding-top:24px}.news-page .site-nav{margin-bottom:22px;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;width:100%;scrollbar-width:none}.news-page .site-nav::-webkit-scrollbar{display:none}.news-top{flex-direction:column;align-items:flex-start}.news-btn{min-height:44px;min-width:44px;padding:0 14px}.news-nav-right{width:100%;justify-content:space-between}.filters{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;scrollbar-width:none;padding-bottom:2px}.filters::-webkit-scrollbar{display:none}.chip{flex:0 0 auto;min-height:44px;height:44px;padding:0 14px;line-height:44px;font-size:12px}.item{grid-template-columns:1fr;gap:8px}.when{margin-bottom:2px}.ncal{gap:4px}.ncell{min-height:56px;padding:5px}.ncell .d{font-size:11px}.news-card{padding:14px}.title{font-size:14px}.sum{font-size:13px}}
  </style><main class="news-page">
    ${siteNavigation("news")}
    <div class="news-top">
      <div>
        <p class="eyebrow"><span class="pulse" aria-hidden="true"></span>仅供观察 · 非买卖建议</p>
        <h1>热点财经</h1>
      </div>
      <div class="news-nav-right">
        <button class="news-btn" id="prev-month" type="button">← 上月</button>
        <span class="news-ym" id="month-label">—</span>
        <button class="news-btn" id="next-month" type="button">下月 →</button>
      </div>
    </div>
    <p class="news-lede">小时扫描 · 披露优先。财报、并购、法务以公告为准；舆论可选且非事实。</p>
    <div class="news-meta">
      <span class="live" id="scan-status"><i></i>扫描中…</span>
      <span>overseas 扫盘机</span>
      <span id="month-count">本月 ${total} 条</span>
      <div class="filters" id="filters">
        <button type="button" class="chip on" data-cat="all">全部</button>
        <button type="button" class="chip" data-cat="earnings">财报</button>
        <button type="button" class="chip" data-cat="mna">并购</button>
        <button type="button" class="chip" data-cat="legal">法务</button>
        <button type="button" class="chip dim" data-cat="opinion" title="暂未接入" disabled>舆论 · 暂未接入</button>
      </div>
    </div>
    <section class="news-card">
      <h2>事件日历 <span class="sub">点选日期筛选；色点为事件类别</span></h2>
      <div class="ncal" id="news-cal" aria-label="事件日历"></div>
      <div class="legend">
        <span><i class="dot earn"></i>财报</span>
        <span><i class="dot mna"></i>并购</span>
        <span><i class="dot legal"></i>法务</span>
        <span><i class="dot social"></i>舆论（暂未接入）</span>
        <span>格内数字=当日条数</span>
      </div>
    </section>
    <section class="news-card">
      <h2>事件时间线 <span class="sub" id="tl-sub">最近事件</span></h2>
      <div class="tl" id="timeline"></div>
    </section>
    <div class="news-foot">
      <span>仅供观察，不构成投资建议。内容来自公开披露与媒体转载，请以原文为准。</span>
      <span>巴小卡 · /news · ${WORKER_BUILD}</span>
    </div>
  </main><script>(()=>{
    const DATA=${payload};
    const events=Array.isArray(DATA.events)?DATA.events.slice():[];
    const byDay=DATA.by_day||{};
    const catLabel={earnings:"财报",mna:"并购",legal:"法务",opinion:"舆论"};
    const catClass={earnings:"earn",mna:"mna",legal:"legal",opinion:"social"};
    const cal=document.getElementById("news-cal");
    const timeline=document.getElementById("timeline");
    const monthLabel=document.getElementById("month-label");
    const tlSub=document.getElementById("tl-sub");
    const scanStatus=document.getElementById("scan-status");
    const monthCount=document.getElementById("month-count");
    const prev=document.getElementById("prev-month");
    const next=document.getElementById("next-month");
    let filter="all";
    let selected="";
    const months=[...new Set(events.map(e=>String(e.date||"").slice(0,7)).filter(Boolean))].sort();
    let month=months.length?months[months.length-1]:new Date().toISOString().slice(0,7);
    function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));}
    function fmtScan(){
      const raw=DATA.scanned_at||DATA.generated_at||"";
      const t=Date.parse(raw);
      if(!Number.isFinite(t)){scanStatus.innerHTML="<i></i>最近扫描 —";return;}
      const age=Date.now()-t;
      const d=new Date(t);
      const txt=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(d);
      if(age>3600*1000){scanStatus.className="live stale";scanStatus.innerHTML="<i></i>超过一小时未更新 · "+esc(txt);}
      else{scanStatus.className="live";scanStatus.innerHTML="<i></i>最近扫描 "+esc(txt);}
    }
    function filteredAll(){
      return events.filter(e=>{
        if(filter!=="all"&&e.category!==filter)return false;
        if(e.category==="opinion"&&!DATA.opinion_enabled)return false;
        return true;
      });
    }
    function dayCats(date){
      const list=filteredAll().filter(e=>e.date===date);
      const seen=new Set();
      const order=["earnings","mna","legal","opinion"];
      const dots=[];
      for(const c of order){if(list.some(e=>e.category===c)&&!seen.has(c)){seen.add(c);dots.push(c);}}
      return {count:list.length,cats:dots};
    }
    function renderCal(){
      const parts=month.split("-").map(Number),y=parts[0],m=parts[1];
      const count=new Date(Date.UTC(y,m,0)).getUTCDate();
      const offset=(new Date(Date.UTC(y,m-1,1)).getUTCDay()+6)%7;
      monthLabel.textContent=y+" 年 "+String(m).padStart(2,"0")+" 月";
      const monthEvents=filteredAll().filter(e=>String(e.date).slice(0,7)===month);
      monthCount.textContent="本月 "+monthEvents.length+" 条";
      cal.replaceChildren();
      for(const w of ["一","二","三","四","五","六","日"]){const el=document.createElement("div");el.className="nwd";el.textContent=w;cal.append(el);}
      for(let i=0;i<offset;i++){const blank=document.createElement("div");blank.className="ncell empty";cal.append(blank);}
      for(let day=1;day<=count;day++){
        const date=month+"-"+String(day).padStart(2,"0");
        const btn=document.createElement("button");
        btn.type="button";btn.className="ncell";
        const wd=new Date(Date.UTC(y,m-1,day)).getUTCDay();
        if(wd===0||wd===6)btn.classList.add("out");
        if(date===selected)btn.classList.add("sel");
        const d=document.createElement("span");d.className="d";d.textContent=String(day);
        const {count:n,cats}=dayCats(date);
        const dots=document.createElement("div");dots.className="dots";
        for(const c of cats.slice(0,4)){const i=document.createElement("i");i.className="dot "+(catClass[c]||"earn");dots.append(i);}
        const cnt=document.createElement("span");cnt.className="ncnt";
        cnt.textContent=n?String(n):"—";
        if(!n)cnt.style.color="#59616a";
        btn.append(d,dots,cnt);
        btn.addEventListener("click",()=>{selected=selected===date?"":date;render();});
        cal.append(btn);
      }
      const idx=months.indexOf(month);
      prev.disabled=idx<=0;next.disabled=idx<0||idx>=months.length-1;
    }
    function timeParts(ev){
      const raw=String(ev.datetime||"");
      const m=raw.match(/T(\\d{2}):(\\d{2})/)||raw.match(/\\s(\\d{2}):(\\d{2})/);
      const clock=m?m[1]+":"+m[2]:"";
      const day=String(ev.date||"").slice(5);
      const prec=ev.time_precision;
      // Date-only sources and legacy fake noon have no displayable clock.
      const dayOnly=prec==="day"||prec==="date"||!clock||(prec!=="minute"&&(clock==="12:00"||clock==="00:00"));
      return {hm:dayOnly?"":clock,day,dayOnly};
    }
    function renderTimeline(){
      const list=filteredAll().filter(e=>!selected||e.date===selected);
      tlSub.textContent=selected?selected+" 的事件":"最近事件";
      timeline.replaceChildren();
      if(!list.length){
        const hint=document.createElement("div");hint.className="empty-hint";
        hint.textContent=selected?"这一天暂无事件":"暂无事件，稍后再看";
        timeline.append(hint);return;
      }
      const show=list.slice(0,80);
      for(const ev of show){
        const art=document.createElement("article");art.className="item";
        const when=document.createElement("div");when.className="when";
        const tp=timeParts(ev);
        when.innerHTML='<span class="day">'+esc(tp.day)+"</span>"+(tp.hm?" "+esc(tp.hm):"");
        const body=document.createElement("div");body.className="body";
        const tags=document.createElement("div");tags.className="tags";
        const tag=document.createElement("span");tag.className="tag "+(catClass[ev.category]||"earn");tag.textContent=catLabel[ev.category]||ev.category;tags.append(tag);
        if(ev.category==="opinion"){const w=document.createElement("span");w.className="tag warn";w.textContent="舆论非事实";tags.append(w);}
        const code=document.createElement("span");code.className="code"+(ev.code?"":" empty");code.textContent=ev.code||"—";tags.append(code);
        if(ev.company){const co=document.createElement("span");co.className="co";co.textContent=ev.company;tags.append(co);}
        const title=document.createElement("h3");title.className="title";title.textContent=ev.title||"";
        const sum=document.createElement("p");sum.className="sum";sum.textContent=ev.summary||"";
        const src=document.createElement("div");src.className="src";
        const site=document.createElement("span");site.className="site";site.textContent=ev.source_name||"来源";
        src.append(site);
        if(ev.source_url){const a=document.createElement("a");a.href=ev.source_url;a.target="_blank";a.rel="noopener noreferrer";a.textContent="原文";src.append(a);}
        body.append(tags,title,sum,src);art.append(when,body);timeline.append(art);
      }
    }
    function render(){renderCal();renderTimeline();}
    document.getElementById("filters").addEventListener("click",(ev)=>{
      const btn=ev.target.closest(".chip");if(!btn||btn.disabled)return;
      filter=btn.getAttribute("data-cat")||"all";
      for(const c of document.querySelectorAll(".chip"))c.classList.toggle("on",c===btn);
      render();
    });
    prev.addEventListener("click",()=>{const i=months.indexOf(month);if(i>0){month=months[i-1];selected="";render();}});
    next.addEventListener("click",()=>{const i=months.indexOf(month);if(i>=0&&i<months.length-1){month=months[i+1];selected="";render();}});
    fmtScan();render();
  })()</script>`;
}


function top5ModelBody(data: LatestPicks, key: PickModelKey): string {
  const block = key === "gpt" ? (data.models?.gpt ?? data.daily_picks) : data.models?.[key];
  const label = pickModelLabel(key);
  if (!block) {
    if (key === "gpt") return `<p class="top5-sub">暂无 daily_picks · ${escapeHtml(FALLBACK_NO_EXPLAIN)}</p>`;
    return `<p class="top5-sub top5-empty-model">${escapeHtml(emptyBackfillingCopy(label))}</p>`;
  }
  const source = block.source || "rule_order";
  const isLlm = source === "llm_rerank";
  const symbols = Array.isArray(block.symbols) ? block.symbols.slice(0, 5) : [];
  const blockDate = escapeHtml(block.date || scanDate(data));
  const isBackfillBlock = block.backfill === true;
  // Backfill blocks never use data.quotes (it belongs to the live scan pool, not these picks).
  const sdq = isBackfillBlock && block.signal_day_quotes && block.signal_day_quotes.as_of === block.date && block.signal_day_quotes.unit === "percent"
    ? block.signal_day_quotes.items || {} : null;
  if (source === "paused" || block.pick_status === "paused" || block.paused === true) {
    // pause_reason stays in data only; never rendered.
    if (block.backfill === true) return `<p class="top5-sub top5-paused">${escapeHtml(detailPausedBodyBackfill(block.date || scanDate(data)))}</p>`;
    return `<p class="top5-sub top5-paused">信号日 ${blockDate} · 当天暂停推荐，下一个交易日开盘不买入</p>`;
  }
  if (!symbols.length) {
    return `<p class="top5-sub">暂无 daily_picks · ${escapeHtml(FALLBACK_NO_EXPLAIN)}</p>`;
  }
  const cards = symbols.map((pick) => {
    const code = escapeHtml(pick.code);
    const name = escapeHtml(pick.name || "");
    const quote = data.quotes?.[pick.code];
    const reason = (pick.reason || "").trim();
    const explain = (pick.explain || "").trim();
    const showFallback = !isLlm || !explain;
    const reasonChip = !showFallback && reason
      ? `<span class="reason-chip" title="${escapeHtml(LABEL_EXPLAIN)}">${escapeHtml(reason)}</span>`
      : `<span class="reason-chip reason-chip-fallback">${escapeHtml(FALLBACK_NO_EXPLAIN)}</span>`;
    const explainHtml = showFallback
      ? `<p class="explain-body explain-fallback">${escapeHtml(FALLBACK_NO_EXPLAIN)}</p>`
      : `<p class="explain-body">${escapeHtml(explain)}</p>`;
    const href = `/s/${pick.code}`;
    const change = formatQuotePercent(quoteFractionToPercent(quote?.chg_pct), 1);
    let quoteRow = `<div class="top5-quote"><span>涨跌 ${change}</span></div>`;
    if (isBackfillBlock) {
      const real = sdq ? sdq[pick.code]?.chg_pct : undefined;
      quoteRow = finiteNumber(real)
        ? `<div class="top5-quote"><span>${escapeHtml(String(block.date || "").slice(5))} 涨跌 ${formatQuotePercent(real, 2)}</span></div>`
        : "";
    }
    return `<article class="top5-card"><a class="top5-id" href="${href}"><b>${code}</b><span>${name}</span></a><div class="top5-reason-row"><span class="explain-lab">${escapeHtml(LABEL_EXPLAIN)}</span>${reasonChip}</div>${explainHtml}${quoteRow}</article>`;
  }).join("");
  const bfTag = block.backfill === true ? `<span class="bf-tag" title="事后补算：只用到当天收盘为止的数据">回溯</span>` : "";
  const bfTip = isBackfillBlock ? `<p class="top5-bf-tip" role="note">${escapeHtml(homeBackfillNote(symbols.length, block.date || scanDate(data)))}</p>` : "";
  return `<p class="top5-sub">信号日 ${blockDate}${bfTag} · 短观察窗，不构成买卖建议</p>${bfTip}<div class="top5-grid">${cards}</div>`;
}

function dailyPicksPanel(data: LatestPicks, model: PickModelKey): string {
  const panes = PICK_MODELS.map((m) => `<div class="top5-model" data-model="${m.key}"${m.key === model ? "" : " hidden"}>${top5ModelBody(data, m.key)}</div>`).join("");
  return `<section class="panel top5-panel" aria-label="每日 Top5"><header class="top5-head"><div class="top5-title-row"><h2>今日 Top5</h2><p class="top5-model-sub">${escapeHtml(MODEL_GPT_NAME)}</p></div></header>${panes}</section>`;
}

function modelSwitchScript(): string {
  // Shared: always GPT; ?model=claude → GPT
return `function sxReadModel(){try{const q=new URLSearchParams(location.search).get("model");localStorage.setItem("${MODEL_STORAGE_KEY}","gpt");if(q&&q!=="gpt"){const u=new URL(location.href);u.searchParams.set("model","gpt");history.replaceState(null,"",u.toString())}}catch(e){}return "gpt"}function sxSaveModel(k){try{localStorage.setItem("${MODEL_STORAGE_KEY}","gpt")}catch(e){}try{const u=new URL(location.href);u.searchParams.set("model","gpt");history.replaceState(null,"",u.toString())}catch(e){}}function sxSyncModelUi(k){for(const a of document.querySelectorAll("a[data-model-link]")){a.setAttribute("href",a.getAttribute("data-model-link")+"?model=gpt")}}`;
}

function picksView(data: LatestPicks, view: HomeView, model: PickModelKey = "gpt"): string {
  const selectedSymbols = [...new Set(data.strategies.flatMap((strategy) => strategy.symbols))];
  const strategyTotal = data.strategies.reduce((sum, strategy) => sum + strategy.symbols.length, 0);
  const content = view === "strategy" ? strategyCards(data) : groupedCards(data, view, selectedSymbols);
  const groupCount = view === "strategy" ? data.strategies.length : view === "industry" ? industryGroups(data, selectedSymbols).length : BOARD_GROUPS.length;
  const groupLabel = view === "strategy" ? "策略" : view === "industry" ? "行业" : "板块";
  const total = view === "strategy" ? strategyTotal : selectedSymbols.length;
  return `<style>${MODEL_SWITCH_CSS}.top5-title-row{display:flex;align-items:center;flex-wrap:wrap;gap:10px 14px}.top5-title-row h2{margin:0}.top5-model>.top5-sub{margin:0 0 14px}.top5-bf-tip{margin:-4px 0 14px;padding:8px 12px;border:1px dashed #7d88d8;border-radius:10px;background:rgba(125,136,216,.08);color:#c9cffc;font-size:13px;line-height:1.5}.top5-empty-model{color:#9aa8ff}@media(max-width:480px){.top5-head>div.top5-title-row{width:100%}}.top5-sub .bf-tag{display:inline-block;margin-left:8px;padding:0 7px;border:1px dashed #7d88d8;border-radius:999px;color:#b9c1ff;background:rgba(154,168,255,.08);font:600 11px/1.6 "PingFang SC",sans-serif}.top5-paused{color:#f0b429}.view-tabs{display:flex;gap:4px;width:max-content;margin-top:18px;padding:4px;border:1px solid var(--line);border-radius:10px;background:#0b0f12}.view-tabs a{display:grid;place-items:center;min-width:72px;min-height:44px;padding:0 14px;border-radius:7px;color:var(--muted);font-size:13px;text-decoration:none}.view-tabs a:hover{color:#dce3e6;background:#141a1f}.view-tabs a.active{color:var(--accent);background:rgba(111,227,162,.1);box-shadow:inset 0 0 0 1px #315d47}.group-title{display:flex;align-items:center;gap:9px}.masthead-side{display:flex;align-items:flex-end;gap:24px}.scan-date{display:grid;gap:3px;padding:10px 14px;border:1px solid #315641;border-radius:10px;background:rgba(111,227,162,.06)}.scan-date span{color:#9ba5aa;font-size:11px;letter-spacing:.08em}.scan-date strong{color:var(--accent);font:700 20px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}.strategy-list-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:0 0 10px}.strategy-list-head h2{font-size:16px}.strategy-list-head span{color:var(--accent);font:650 12px ui-monospace,SFMono-Regular,Menlo,monospace}.group-hint,.view-hint{color:var(--muted);font:11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.view-hint{margin:10px 0 0}.top5-panel{padding:18px 20px;margin-bottom:12px}.top5-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}.top5-head h2{margin:0 0 4px}.top5-sub{margin:0;color:var(--muted);font-size:12px;line-height:1.5}.top5-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.top5-card{display:grid;gap:8px;padding:12px;border:1px solid #29333b;border-radius:10px;background:#0b0f12}.top5-id{display:flex;align-items:baseline;gap:8px;color:inherit;text-decoration:none;font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.top5-id b{color:#f2f5f6;letter-spacing:.04em}.top5-id span{color:#919ca5;font-family:Inter,ui-sans-serif,"PingFang SC",sans-serif;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.top5-id:hover b{color:var(--accent)}.top5-reason-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px}.explain-lab{color:#7f8a91;font:650 10px/1 "PingFang SC",sans-serif;letter-spacing:.04em}.reason-chip{flex:0 1 auto;max-width:100%;padding:4px 9px;border:1px solid #3a4f44;border-radius:999px;color:#d7efe3;background:rgba(111,227,162,.1);font:650 11px/1.3 "PingFang SC",Inter,sans-serif}.reason-chip-fallback{border-color:#3a4248;color:#9aa3ab;background:#12161a}.explain-body{margin:0;color:#c5cdd3;font:12px/1.65 "PingFang SC",Inter,sans-serif}.explain-fallback{color:#8b949c}.top5-quote{color:#69737c;font:10px ui-monospace,Menlo,monospace}@media(max-width:899px){.masthead-side{width:100%;justify-content:space-between;align-items:flex-start}.view-tabs{width:100%;max-width:100%}.view-tabs a{flex:1;min-width:0;min-height:44px}.top5-grid{grid-template-columns:1fr 1fr}}@media(max-width:599px){.masthead-side{align-items:stretch;flex-direction:column;gap:14px}.scan-date{width:max-content}.strategy-list-head{align-items:flex-start;flex-direction:column;gap:3px}.view-tabs{overflow-x:auto;-webkit-overflow-scrolling:touch;flex-wrap:nowrap;scrollbar-width:none}.view-tabs::-webkit-scrollbar{display:none}.view-tabs a{flex:1 0 auto;min-width:72px}.top5-grid{grid-template-columns:1fr}.top5-panel{padding:14px}}</style><main>
    ${siteNavigation("home", model)}
    <header class="masthead"><div><p class="eyebrow"><span class="pulse" aria-hidden="true"></span>A 股策略观察</p><h1>巴小卡股市监控</h1></div><div class="masthead-side"><div class="scan-date" aria-label="扫盘日期"><span>扫盘日期</span><strong>${escapeHtml(scanDate(data))}</strong></div><dl class="summary"><div><dt>${groupLabel}</dt><dd>${groupCount}</dd></div><div><dt>入选</dt><dd>${total}</dd></div></dl></div></header>
    ${viewTabs(view)}
    <p class="view-hint">${escapeHtml(viewHint(view))}</p>
    <div class="meta"><span>扫盘日期 ${escapeHtml(scanDate(data))} · 更新于 ${escapeHtml(formatShanghaiTime(data.generated_at))} · 相对上一交易日；收盘价为最近交易日；价格与涨跌均按不复权行情</span><span class="mode">${escapeHtml(MODE_LABELS[data.mode] ?? "其他")}</span></div>
    ${dailyPicksPanel(data, model)}
    <div class="strategy-list-head"><h2>策略扫描</h2><span>扫盘日期 ${escapeHtml(scanDate(data))}</span></div>
    <div class="strategy-list">${content}</div>${footer()}</main><script>(()=>{${modelSwitchScript()}const panes=[...document.querySelectorAll(".top5-model")];function apply(k){for(const p of panes)p.hidden=p.getAttribute("data-model")!==k;sxSyncModelUi(k)}apply(sxReadModel());})()</script>`;
}

function strategyCards(data: LatestPicks): string {
  return data.strategies.map((strategy, index) => `
    <section class="strategy" aria-labelledby="strategy-${index}">
      <header class="strategy-head"><div class="strategy-title"><h2 id="strategy-${index}">${escapeHtml(strategyLabel(strategy.name))}</h2><button class="help-toggle" type="button" aria-label="策略说明" aria-expanded="false" aria-controls="strategy-help-${index}">?</button></div><span class="count">${strategy.symbols.length}</span></header>
      ${strategyHelp(strategy.name, index)}
      <div class="symbols">${symbolsMarkup(data, strategy.symbols)}</div>
    </section>`).join("");
}

interface PickGroup { key: string; label: string; hint: string; symbols: string[] }

function groupedCards(data: LatestPicks, view: "industry" | "board", symbols: string[]): string {
  const groups = view === "industry" ? industryGroups(data, symbols) : boardGroups(data, symbols);
  return groups.map((group, index) => `
    <section class="strategy" aria-labelledby="${view}-${index}">
      <header class="strategy-head"><div class="group-title"><h2 id="${view}-${index}">${escapeHtml(group.label)}</h2><span class="group-hint">${escapeHtml(group.hint)}</span></div><span class="count">${group.symbols.length}</span></header>
      <div class="symbols">${symbolsMarkup(data, group.symbols)}</div>
    </section>`).join("");
}

function symbolsMarkup(data: LatestPicks, symbols: string[]): string {
  if (!symbols.length) return '<span class="empty">本期无入选标的</span>';
  const hitsBySymbol = symbolStrategyHits(data);
  const visible = symbols.slice(0, CHIP_PREVIEW);
  const rest = symbols.slice(CHIP_PREVIEW);
  const visibleHtml = visible.map((symbol) => symbolLink(symbol, data.names?.[symbol], data.quotes?.[symbol], hitsBySymbol.get(symbol) ?? [])).join("");
  if (!rest.length) return visibleHtml;
  // Compact overflow payload (not full cards) — client expands to same symbol DOM.
  const payload = rest.map((symbol) => {
    const quote = data.quotes?.[symbol];
    return [
      symbol,
      data.names?.[symbol] ?? "",
      quote?.close ?? null,
      quoteFractionToPercent(quote?.chg_pct),  // client pct() expects percent
      quote?.volume ?? null,
      quoteFractionToPercent(quote?.vol_chg_pct),
      hitsBySymbol.get(symbol) ?? [],
    ];
  });
  const json = JSON.stringify(payload).replace(/</g, "\u003c").replace(/>/g, "\u003e").replace(/&/g, "\u0026");
  return `${visibleHtml}<script type="application/json" class="symbols-more-data">${json}</script><button class="expand-more" type="button">展开更多（${rest.length}）</button>`;
}

function symbolStrategyHits(data: LatestPicks): Map<string, string[]> {
  const hits = new Map<string, string[]>();
  for (const strategy of data.strategies) {
    const label = strategyLabel(strategy.name);
    for (const symbol of strategy.symbols) {
      const existing = hits.get(symbol);
      if (existing) {
        if (!existing.includes(label)) existing.push(label);
      } else {
        hits.set(symbol, [label]);
      }
    }
  }
  return hits;
}

function industryGroups(data: LatestPicks, symbols: string[]): PickGroup[] {
  const grouped = new Map<string, PickGroup>();
  for (const symbol of symbols) {
    const meta = data.meta?.[symbol];
    const groupName = (meta?.industry_group || meta?.sw_l1 || "").trim() || "未分类";
    const swL2 = (meta?.sw_l2 || "").trim();
    const swL1Code = (meta?.sw_l1_code || "").trim();
    const hint = swL2
      ? (groupName === "半导体" ? `申万二级 · ${swL2}` : `申万 · ${swL2}`)
      : (swL1Code || (groupName === "未分类" ? "无申万成分" : "申万一级"));
    const group = grouped.get(groupName) ?? {
      key: groupName,
      label: groupName,
      hint,
      symbols: [],
    };
    group.symbols.push(symbol);
    grouped.set(groupName, group);
  }
  if (!grouped.size) grouped.set("未分类", { key: "未分类", label: "未分类", hint: "无申万成分", symbols: [] });
  const rank = new Map(SW_INDUSTRY_ORDER.map((name, index) => [name, index]));
  return [...grouped.values()].sort((left, right) => {
    if (left.key === "未分类") return 1;
    if (right.key === "未分类") return -1;
    const leftRank = rank.has(left.key) ? rank.get(left.key)! : 10_000;
    const rightRank = rank.has(right.key) ? rank.get(right.key)! : 10_000;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return left.label.localeCompare(right.label, "zh-CN");
  });
}
function boardGroups(data: LatestPicks, symbols: string[]): PickGroup[] {
  const grouped = new Map(BOARD_GROUPS.map((group) => [group.name, { key: group.name, label: group.name, hint: group.hint, symbols: [] as string[] }]));
  for (const symbol of symbols) {
    const candidate = data.meta?.[symbol]?.board;
    const board = isBoardName(candidate) ? candidate : deriveBoard(symbol);
    grouped.get(board)!.symbols.push(symbol);
  }
  return BOARD_GROUPS.map((group) => grouped.get(group.name)!);
}

function deriveBoard(symbol: string, market = inferMarket(symbol)): BoardName {
  if (symbol.startsWith("688")) return "科创板";
  if (symbol.startsWith("300") || symbol.startsWith("301")) return "创业板";
  if (symbol.startsWith("8") || symbol.startsWith("4") || market === "BJ") return "北交所";
  if (symbol.startsWith("60")) return "沪市主板";
  if (market === "SZ") return "深市主板";
  return "其他";
}

function isBoardName(value: string | undefined): value is BoardName {
  return BOARD_GROUPS.some((group) => group.name === value);
}

function inferMarket(symbol: string): string {
  if (symbol.startsWith("8") || symbol.startsWith("4") || symbol.startsWith("92")) return "BJ";
  if (symbol.startsWith("5") || symbol.startsWith("6") || symbol.startsWith("9")) return "SH";
  return /^\d{6}$/.test(symbol) ? "SZ" : "";
}

function homeView(value: string | null): HomeView {
  return HOME_VIEWS.includes(value as HomeView) ? value as HomeView : "strategy";
}

function viewHint(view: HomeView): string {
  if (view === "industry") return "按申万行业分类";
  if (view === "board") return "按上市板块";
  return "按选股策略";
}

function viewTabs(active: HomeView): string {
  const labels: Record<HomeView, string> = { strategy: "策略", industry: "行业", board: "板块" };
  return `<nav class="view-tabs" aria-label="分组方式">${HOME_VIEWS.map((view) => `<a href="/?view=${view}"${view === active ? ' class="active" aria-current="page"' : ""}>${labels[view]}</a>`).join("")}</nav>`;
}

function stockDetailView(data: StockDetail): string {
  const validBars = data.ohlcv_60d.filter((bar) => finiteNumber(bar.close));
  const latest = validBars.at(-1)?.close ?? null;
  const previous = validBars.at(-2)?.close ?? null;
  const change = latest !== null && previous !== null ? latest - previous : null;
  const percent = change !== null && previous !== null && previous !== 0 ? change / previous : null;
  const direction = change === null ? "" : change > 0 ? "positive" : change < 0 ? "negative" : "neutral";
  const price = latest === null ? "暂无" : formatPrice(latest);
  const delta = change === null || percent === null ? "暂无" : `${signed(change, 2)} (${signed(percent * 100, 2)}%)`;
  const name = data.name || "暂无";
  return `<main class="detail-page">
    <nav class="detail-nav"><a class="back-link" href="/">← 返回列表</a><span class="mode">个股详情</span></nav>
    <header class="stock-head"><div><h1>${escapeHtml(data.symbol)}</h1><div class="stock-name">${escapeHtml(name)} <span class="market">${escapeHtml(marketLabel(data.market))}</span></div></div><div class="quote"><strong>${price}</strong><span class="${direction}">${delta}</span></div></header>
    <div class="overview-grid">
      <section class="panel company"><h2>公司概况</h2><dl><div><dt>简称</dt><dd>${valueText(data.name)}</dd></div><div><dt>行业</dt><dd>${valueText(data.industry)}</dd></div><div><dt>主营</dt><dd>${valueText(data.main_business)}</dd></div><div><dt>上市日</dt><dd>${valueText(data.ipo_date)}</dd></div></dl></section>
      <section class="panel picked"><h2>本期入选</h2><div class="pick-tags">${data.picked_strategies.length ? data.picked_strategies.map((strategy) => `<span>${escapeHtml(strategyLabel(strategy))}</span>`).join("") : '<span class="empty">暂无</span>'}</div><p class="note">来自当日 latest.json 策略命中。</p></section>
    </div>
    <section class="panel chart-panel"><header class="chart-head"><div><h2>近 60 日走势</h2><p>价格按不复权行情</p></div><a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></header>${chartView(data.ohlcv_60d)}</section>
    <section class="panel report-panel"><h2>上一期财报</h2>${lastReportView(data.last_report)}<p class="note">金额按元数据换算展示；缺数据时显示「暂无」。</p></section>
    <section class="panel reports"><h2>近期公开财报</h2>${recentReportsView(data.recent_reports)}</section>${footer()}</main>`;
}

function chartView(bars: OhlcvBar[]): string {
  const chartBars = bars.flatMap((bar) => {
    const date = normalizeTradingDate(bar.date);
    if (!date || !finiteNumber(bar.open) || !finiteNumber(bar.high) || !finiteNumber(bar.low) || !finiteNumber(bar.close)) return [];
    return [{ date, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: finiteNumber(bar.volume) ? bar.volume : null }];
  });
  if (!chartBars.length) return '<div class="chart-empty">暂无</div>';
  const serializedBars = JSON.stringify(chartBars)
    .replace(/&/g, "\\u0026")
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e");
  return `<div class="kx-shell"><div id="kx" role="img" aria-label="近 60 日 K 线和成交量图"></div><div class="kx-stats" id="kx-stats" aria-live="polite"><span class="kx-date" id="kx-date">最新交易日</span><span><small>开</small><strong id="kx-open">—</strong></span><span><small>高</small><strong id="kx-high">—</strong></span><span><small>低</small><strong id="kx-low">—</strong></span><span><small>收</small><strong id="kx-close">—</strong></span><span><small>量</small><strong id="kx-volume">—</strong></span></div></div><script src="https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script><script>(()=>{
    const bars=${serializedBars};
    const container=document.getElementById("kx");
    const lib=window.LightweightCharts;
    if(!container||!lib){if(container){container.className="kx-load-error";container.textContent="图表加载失败"}return}
    const chart=lib.createChart(container,{autoSize:true,height:360,layout:{background:{type:lib.ColorType.Solid,color:"#090d10"},textColor:"#6f7b84",fontFamily:'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',fontSize:11,panes:{separatorColor:"#202930",separatorHoverColor:"#315641",enableResize:false}},grid:{vertLines:{color:"rgba(38,48,57,.26)"},horzLines:{color:"#202930"}},leftPriceScale:{visible:false},rightPriceScale:{visible:true,borderColor:"#202930",scaleMargins:{top:.08,bottom:.08}},timeScale:{borderColor:"#202930",rightOffset:2,barSpacing:10,minBarSpacing:4,fixLeftEdge:true,fixRightEdge:true,tickMarkFormatter:timeLabel},crosshair:{mode:lib.CrosshairMode.Normal,vertLine:{color:"#52616c",width:1,style:lib.LineStyle.Dashed,labelBackgroundColor:"#315641"},horzLine:{color:"#52616c",width:1,style:lib.LineStyle.Dashed,labelBackgroundColor:"#315641"}},localization:{locale:"zh-CN",priceFormatter:(value)=>Number(value).toFixed(2)}});
    const candles=chart.addSeries(lib.CandlestickSeries,{upColor:"#6fe3a2",downColor:"#ff6b6b",borderUpColor:"#6fe3a2",borderDownColor:"#ff6b6b",wickUpColor:"#6fe3a2",wickDownColor:"#ff6b6b",priceLineVisible:false,lastValueVisible:true});
    const volumes=chart.addSeries(lib.HistogramSeries,{priceScaleId:"",priceFormat:{type:"volume"},priceLineVisible:false,lastValueVisible:false},1);
    candles.setData(bars.map((bar)=>({time:bar.date,open:bar.open,high:bar.high,low:bar.low,close:bar.close})));
    volumes.setData(bars.filter((bar)=>bar.volume!==null).map((bar)=>({time:bar.date,value:bar.volume,color:bar.close>=bar.open?"#6fe3a2":"#ff6b6b"})));
    volumes.priceScale().applyOptions({scaleMargins:{top:.08,bottom:0}});
    const panes=chart.panes();
    if(panes[0])panes[0].setStretchFactor(7);
    if(panes[1])panes[1].setStretchFactor(3);
    chart.timeScale().fitContent();
    const byDate=new Map(bars.map((bar)=>[bar.date,bar]));
    const latest=bars[bars.length-1];
    const fields={date:document.getElementById("kx-date"),open:document.getElementById("kx-open"),high:document.getElementById("kx-high"),low:document.getElementById("kx-low"),close:document.getElementById("kx-close"),volume:document.getElementById("kx-volume")};
    const render=(bar)=>{fields.date.textContent=bar.date;fields.open.textContent=price(bar.open);fields.high.textContent=price(bar.high);fields.low.textContent=price(bar.low);fields.close.textContent=price(bar.close);fields.volume.textContent=volume(bar.volume)};
    render(latest);
    chart.subscribeCrosshairMove((param)=>{if(!param.time){render(latest);return}const bar=byDate.get(timeKey(param.time));render(bar||latest)});
    function price(value){return Number(value).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2})}
    function volume(value){if(value===null)return "暂无";const absolute=Math.abs(value);if(absolute>=100000000)return trim(value/100000000,2)+" 亿";if(absolute>=10000)return trim(value/10000,1)+" 万";return Math.round(value).toLocaleString("zh-CN")}
    function trim(value,digits){return value.toFixed(digits).replace(/\\.0+$/,"").replace(/(\\.\\d*[1-9])0+$/,"$1")}
    function timeKey(time){if(typeof time==="string")return time;if(typeof time==="number")return new Date(time*1000).toISOString().slice(0,10);return String(time.year)+"-"+String(time.month).padStart(2,"0")+"-"+String(time.day).padStart(2,"0")}
    function timeLabel(time){const key=timeKey(time);return key.slice(5).replace("-","/")}
  })()</script>`;
}

function normalizeTradingDate(value: string): string | null {
  const match = value.trim().match(/^(\d{4})[-\/]?(\d{2})[-\/]?(\d{2})/);
  if (!match) return null;
  return `${match[1]}-${match[2]}-${match[3]}`;
}

function lastReportView(report: ProfitReport | null): string {
  if (!report) return '<div class="report-empty">暂无</div>';
  const cells: Array<[string, string]> = [["报告期", reportLabel(report.stat_date)], ["披露日", valueText(report.pub_date)], ["营业总收入", formatAmount(report.revenue)], ["归母净利", formatAmount(report.net_profit)], ["营收同比", formatPercent(report.yoy_revenue)], ["净利同比", formatPercent(report.yoy_net_profit)]];
  return `<div class="report-grid">${cells.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("")}</div>`;
}

function recentReportsView(reports: ProfitReport[]): string {
  if (!reports.length) return '<div class="report-empty">暂无</div>';
  return `<div class="report-list">${reports.slice(0, 3).map((report) => `<div><strong>${reportLabel(report.stat_date)}</strong><span>${reportType(report.stat_date)}</span><time>${valueText(report.pub_date)}</time></div>`).join("")}</div>`;
}

function symbolLink(symbol: string, name?: string, snapshot?: QuoteSnapshot, hitLabels: string[] = []): string {
  const label = name ? `${symbol} ${name}` : symbol;
  const close = snapshot?.close;
  const quote = finiteNumber(close) ? formatPrice(close) : "暂无";
  const change = formatQuotePercent(quoteFractionToPercent(snapshot?.chg_pct), 1);
  const volume = formatCompactVolume(snapshot?.volume);
  const volumeChange = formatQuotePercent(quoteFractionToPercent(snapshot?.vol_chg_pct), 0);
  const hitsHtml = hitLabels.length
    ? `<span class="symbol-hits">${hitLabels.map((hit) => `<span class="hit-chip">${escapeHtml(hit)}</span>`).join("")}</span>`
    : "";
  const hitsNote = hitLabels.length ? `，策略 ${hitLabels.join("、")}` : "";
  const contents = `<span class="symbol-head"><span class="symbol-id"><b>${escapeHtml(symbol)}</b>${name ? `<span>${escapeHtml(name)}</span>` : ""}</span>${hitsHtml}</span><span class="symbol-metrics"><span><small>收盘</small><strong>${quote}</strong></span><span><small>涨跌</small><strong class="${directionClass(snapshot?.chg_pct)}">${change}</strong></span><span><small>成交量</small><strong>${volume}</strong></span><span><small>量涨跌</small><strong class="${directionClass(snapshot?.vol_chg_pct)}">${volumeChange}</strong></span></span>`;
  if (!/^\d{6}$/.test(symbol)) return `<span class="symbol">${contents}</span>`;
  return `<a class="symbol" href="/s/${symbol}" aria-label="查看 ${escapeHtml(label)} 详情，收盘 ${quote}，涨跌 ${change}，成交量 ${volume}，量涨跌 ${volumeChange}${escapeHtml(hitsNote)}">${contents}</a>`;
}

function strategyHelp(name: string, index: number): string {
  const help = STRATEGY_HELP[name];
  const content = help
    ? `<p><strong>一句话：</strong>${escapeHtml(help.first)}</p><p><strong>说明：</strong>${escapeHtml(help.second)}</p>`
    : "<p>暂无说明</p>";
  return `<div class="strategy-help" id="strategy-help-${index}" hidden>${content}</div>`;
}
function strategyLabel(name: string): string { return STRATEGY_LABELS[name] ?? name; }
function marketLabel(market: string): string { return ({ SH: "沪市", SZ: "深市", BJ: "北交所" } as Record<string, string>)[market] ?? market; }
function reportLabel(date: string | null): string {
  if (!date) return "暂无";
  const match = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return escapeHtml(date);
  const suffix: Record<string, string> = { "03": "一季报", "06": "中报", "09": "三季报", "12": "年报" };
  return `${match[1]} ${suffix[match[2]] ?? "财报"}`;
}
function reportType(date: string | null): string {
  if (!date) return "暂无";
  return ({ "03": "一季度报告", "06": "半年度报告", "09": "三季度报告", "12": "年度报告" } as Record<string, string>)[date.slice(5, 7)] ?? "公开财报";
}
function valueText(value: unknown): string { return value === null || value === undefined || value === "" ? "暂无" : escapeHtml(String(value)); }
function finiteNumber(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function formatPrice(value: number): string { return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value); }
function signed(value: number, digits: number): string { return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}`; }
/** 0.13.4: latest.quotes chg_pct / vol_chg_pct are FRACTIONS (0.0178 = +1.78%), written only by
 *  export_details.quote_from_bars ((close - prev) / prev). Convert explicitly before formatting.
 *  (signal_day_quotes on backfill blocks are already percent, unit="percent"; never pass them here.) */
function quoteFractionToPercent(value: number | null | undefined): number | null {
  return finiteNumber(value) ? value * 100 : null;
}
function formatQuotePercent(value: number | null | undefined, digits: number): string {
  return finiteNumber(value) ? `${value > 0 ? "+" : value < 0 ? "-" : ""}${Math.abs(value).toFixed(digits)}%` : "暂无";
}
function directionClass(value: number | null | undefined): string { return !finiteNumber(value) ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "neutral"; }
function formatCompactVolume(value: number | null | undefined): string {
  if (!finiteNumber(value)) return "暂无";
  const absolute = Math.abs(value);
  if (absolute >= 100_000_000) return `${trimTrailingZero(value / 100_000_000, 1)}亿`;
  if (absolute >= 10_000) return `${trimTrailingZero(value / 10_000, absolute >= 10_000_000 ? 0 : 1)}万`;
  return Math.round(value).toLocaleString("zh-CN");
}
function trimTrailingZero(value: number, digits: number): string { return value.toFixed(digits).replace(/\.0+$/, ""); }
function formatAmount(value: number | null): string {
  if (!finiteNumber(value)) return "暂无";
  const amount = value / 100_000_000, digits = Math.abs(amount) >= 100 ? 0 : Math.abs(amount) >= 10 ? 1 : 2;
  return `${amount < 0 ? "−" : ""}${Math.abs(amount).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })} 亿`;
}
function formatPercent(value: number | null): string { return finiteNumber(value) ? `${signed(value * 100, 1)}%` : "暂无"; }
/**
 * Path B — POST /api/nl-analyze (default: DSH Agent + filesystem skills via local bridge).
 *
 * No intent hard-routing. LLM function-calling drives QBS tools; artifacts → Report JSON.
 * See docs/NL_ANALYZE.md.
 */
interface NlAnalyzeRequest {
  query: string;
  assets?: string[];
  locale?: string;
}
interface NlAnalyzeSection { heading: string; body_md: string }
interface NlAnalyzeTable {
  title?: string;
  name?: string;
  columns: string[];
  rows: Array<Array<string | number | null>>;
}
interface NlAnalyzeSource {
  name?: string;
  url?: string;
  provider?: string;
  endpoint?: string;
  tool?: string;
  task_id?: string;
}
interface NlAnalyzeKpis {
  close?: string;
  change_pct?: number;
  change?: string;
  amount?: string;
}
interface NlAnalyzeSeries {
  name: string;
  dates: Array<string | number>;
  values: Array<number | null>;
}
interface NlAnalyzeChart {
  name: string;
  mime: string;
  data_base64: string;
  url: string | null;
}
interface NlAnalyzeToolTrace {
  step: number;
  tool: string;
  ok: boolean;
  detail?: string;
  ms?: number;
}
interface NlAnalyzeReport {
  title: string;
  summary_md: string;
  trade_day?: string;
  kpis?: NlAnalyzeKpis;
  sections: NlAnalyzeSection[];
  tables: NlAnalyzeTable[];
  series?: NlAnalyzeSeries[];
  charts?: NlAnalyzeChart[];
  chips?: string[];
  sources?: NlAnalyzeSource[];
  tool_trace?: NlAnalyzeToolTrace[];
  disclaimer: string;
  latency_ms: number;
  risk_lines?: string[];
}
interface NlAnalyzeResponse {
  ok: boolean;
  /** @deprecated not required; kept optional for old clients */
  intent?: string;
  report?: NlAnalyzeReport;
  meta?: Record<string, unknown>;
  error?: { code: string; message: string; retryable?: boolean; tool?: string; upstream?: Record<string, unknown> };
}

const NL_ANALYZE_DISCLAIMER =
  "仅供观察/教育，不构成投资建议。数据来自公开行情与上游接口，请以原文与官方披露为准。";
const NL_ANALYZE_RISK_LINES = [
  "本报告由规则与模型自动生成，仅供观察，不构成投资建议。",
  "行情可能有延迟；请以交易所或券商终端为准。",
  "过往表现不代表未来收益。回测结果依赖假设，不代表实盘。",
] as const;

const QBS_BASE = "https://www.quantbuddy.cn/skill";
const QBS_FAST_QUERY_URL = `${QBS_BASE}/fastQuery`;
const QBS_RUN_MULTI_URL = `${QBS_BASE}/runMultiFormulaBatch`;
const QBS_READ_DATA_URL = `${QBS_BASE}/readData`;
const QBS_CONFIRM_MULTI_URL = `${QBS_BASE}/confirmDataMulti`;
const QBS_RENDER_CHART_URL = `${QBS_BASE}/renderChart`;
const QBS_RENDER_KLINE_URL = `${QBS_BASE}/renderKLine`;
const QBS_SESSION_BEGIN_URL = `${QBS_BASE}/session/begin`;
const QBS_SNAPSHOT_FIELDS = ["收盘价", "涨跌幅", "成交额"] as const;

const SKILL_DIRECT_MAX_STEPS = 8;
const SKILL_DIRECT_TOTAL_MS = 240_000; // align nginx ≥240–300s
const SKILL_DIRECT_TOOL_MS = {
  fast_query: 30_000,
  confirm_data_multi: 30_000,
  run_multi_formula: 120_000,
  read_data: 60_000,
  render_chart: 60_000,
  render_kline: 60_000,
  new_session: 15_000,
} as const;

/** Frozen screen 8 formulas — few-shot example only, NOT a code branch. */
const SCREEN_FEWSHOT_FORMULAS = [
  '基准60高=昨天(最大("全市场每日最高价", 60))',
  '均额20=昨天(平均("全市场每日成交额", 20))',
  '掩码_新高=("全市场每日最高价" > "基准60高")',
  '掩码_放量=("全市场每日成交额" > "均额20" * 2)',
  '掩码_池=板块(万得全A)*缺失填零("非ST股")',
  '涨幅=涨跌幅("全市场每日收盘价")',
  '得分="涨幅"*"掩码_新高"*"掩码_放量"*"掩码_池"',
  'TopN=取前("得分", 10, 返回数值)',
];

const BACKTEST_FEWSHOT = {
  begin_date: 20150101,
  formulas: [
    'Filter=缺失填零("非ST股")*板块(万得全A)',
    'PE_valid="A股市盈率（PE）〔估值数据〕"*("A股市盈率（PE）〔估值数据〕">0)*"Filter"',
    'ROE_ok=("A股净资产收益率ROE">15)*"Filter"',
    'Signal=("PE_valid">0)*(排名("PE_valid",升序)<百分比(板块(万得全A),0.2))*"ROE_ok"',
    'NAV=回测("Signal",当天收盘买入,返回复利净值,信号按列归一)',
    'BenchmarkNAV=回测(指数(000300.SH),当天收盘买入,返回复利净值)',
  ],
  force_reusable_array: ["NAV", "BenchmarkNAV", "Signal"],
};

const NL_ASSET_ALIASES: Array<{ match: RegExp; asset: string; code?: string }> = [
  { match: /贵州茅台|茅台|600519|SH600519|600519\.SH/i, asset: "贵州茅台", code: "600519" },
  { match: /宁德时代|宁德|300750|SZ300750|300750\.SZ/i, asset: "宁德时代", code: "300750" },
];

function resolveQbsApiKey(env: Env): string | undefined {
  const key = (env.QBS_API_KEY || env.QUANT_BUDDY_API_KEY || "").trim();
  return key || undefined;
}

function resolveLlmConfig(env: Env): { apiKey?: string; baseUrl?: string; model?: string } {
  const apiKey = (env.LLM_API_KEY || env.OPENAI_API_KEY || "").trim() || undefined;
  const baseRaw = (env.LLM_API_BASE || env.LLM_BASE_URL || env.OPENAI_BASE_URL || "").trim();
  const model = (env.LLM_MODEL || env.OPENAI_MODEL || "").trim() || undefined;
  const baseUrl = baseRaw ? baseRaw.replace(/\/+$/, "") : undefined;
  return { apiKey, baseUrl, model };
}

function newTaskId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `bxk-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}

/** Metric / field tokens must never be treated as ticker assets. */
function looksLikeMetricOrFieldToken(s: string): boolean {
  const t = s.trim();
  if (!t) return true;
  if (/^(归母|归母净利润|归母净利|净利润|净利|EBITDA|ROE|营收|营业收入|营业总收入|资产负债率|龙虎榜|龙虎榜净买额|GICS|GICS行业|所属行业|行业|收盘价|涨跌幅|成交额|净资产收益率|毛利率|净利率|每股收益|EPS)$/i.test(t)) {
    return true;
  }
  // short phrase dominated by metric words, no 6-digit code
  if (!/\d{6}/.test(t) && t.length <= 16 && /净利润|EBITDA|龙虎榜|GICS|资产负债率|净资产收益率|归母|涨跌幅|成交额|收盘价/.test(t)) {
    return true;
  }
  return false;
}

/** Forbidden silent index substitutes (never invent 万得全A / 881001). */
function looksLikeSilentIndex(s: string): boolean {
  return /881001|万得全A|全A指数|CSI.?全A/i.test(s);
}

function sanitizeAssetList(assets: string[]): string[] {
  return assets
    .map((a) => String(a).trim())
    .filter((a) => a && !looksLikeMetricOrFieldToken(a) && !looksLikeSilentIndex(a));
}

function extractAssetsFromQuery(query: string, assets?: string[]): string[] {
  if (Array.isArray(assets) && assets.length) {
    const cleaned = sanitizeAssetList(assets.map(String));
    if (cleaned.length) return cleaned;
  }
  for (const row of NL_ASSET_ALIASES) {
    if (row.match.test(query)) return [row.asset];
  }
  // Only accept an explicit 6-digit code — never parse metric names after 查一下 as assets.
  const code = query.match(/\b(\d{6})\b/);
  if (code) return [code[1]];
  return [];
}

function displayAssetLabel(asset: string): string {
  for (const row of NL_ASSET_ALIASES) {
    if (row.asset === asset || row.code === asset || row.match.test(asset)) {
      return row.code ? `${row.asset}（${row.code}）` : row.asset;
    }
  }
  return asset;
}

function unwrapQbsScalar(raw: unknown): number | string | null {
  if (raw == null) return null;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string") {
    const t = raw.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : t;
  }
  if (typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    if ("v" in obj) return unwrapQbsScalar(obj.v);
    if ("value" in obj) return unwrapQbsScalar(obj.value);
  }
  return null;
}

function formatCloseDisplay(value: number | string | null): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (typeof value === "string" && value.trim()) return value.trim();
  return "—";
}

function formatChangePctDisplay(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatAmountDisplay(value: number | string | null): string {
  if (typeof value === "number" && Number.isFinite(value)) return formatAmount(value);
  if (typeof value === "string" && value.trim()) return value.trim();
  return "—";
}

interface QbsSnapshotNorm {
  assetName: string;
  ticker: string | null;
  close: number | null;
  changePct: number | null;
  amount: number | null;
  tradeDay: string | null;
  rawAssetKey: string;
}

function unwrapQbsPayload(body: Record<string, unknown>): Record<string, unknown> {
  const data = body.data;
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const inner = data as Record<string, unknown>;
    if ("results" in inner || "success" in inner || "query_type" in inner || "base64" in inner || "last_column_full" in inner) {
      return inner;
    }
  }
  return body;
}

function fieldMapFromAsset(asset: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...asset };
  const fields = asset.fields;
  if (Array.isArray(fields)) {
    for (const item of fields) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      const intent = typeof row.intent === "string" ? row.intent
        : typeof row.name === "string" ? row.name
        : typeof row.field === "string" ? row.field
        : null;
      if (!intent) continue;
      out[intent] = {
        v: row.value ?? row.v,
        d: row.date ?? row.d,
        unit: row.unit,
      };
    }
  }
  return out;
}

function normalizeQbsSnapshot(data: Record<string, unknown>, requestedAssets: string[]): QbsSnapshotNorm | null {
  const payload = unwrapQbsPayload(data);
  const results = Array.isArray(payload.results) ? payload.results
    : Array.isArray(payload.data) ? payload.data
    : [];
  let asset: Record<string, unknown> | null = null;
  let rawKey = requestedAssets[0] || "";
  if (results.length && typeof results[0] === "object" && results[0]) {
    const first = results[0] as Record<string, unknown>;
    // shape: results[{ asset, fields }] or results[{ 贵州茅台: {...} }]
    if (first.fields || first.收盘价 || first.close) {
      asset = fieldMapFromAsset(first);
      rawKey = String(first.asset || first.name || first.ticker || rawKey);
    } else {
      for (const [k, v] of Object.entries(first)) {
        if (v && typeof v === "object") {
          asset = fieldMapFromAsset(v as Record<string, unknown>);
          rawKey = k;
          break;
        }
      }
    }
  }
  if (!asset) {
    // flat map under payload.results as object
    if (payload.results && typeof payload.results === "object" && !Array.isArray(payload.results)) {
      const map = payload.results as Record<string, unknown>;
      for (const [k, v] of Object.entries(map)) {
        if (v && typeof v === "object") {
          asset = fieldMapFromAsset(v as Record<string, unknown>);
          rawKey = k;
          break;
        }
      }
    }
  }
  if (!asset) return null;

  const pick = (...keys: string[]) => {
    for (const k of keys) {
      if (k in asset!) {
        const s = unwrapQbsScalar(asset![k]);
        if (s != null) return s;
      }
    }
    return null;
  };
  const closeRaw = pick("收盘价", "close", "最新价");
  const chgRaw = pick("涨跌幅", "pct_change", "change_pct");
  const amtRaw = pick("成交额", "amount");
  let tradeDay: string | null = null;
  for (const k of ["收盘价", "涨跌幅", "成交额"]) {
    const cell = asset[k];
    if (cell && typeof cell === "object") {
      const d = (cell as Record<string, unknown>).d ?? (cell as Record<string, unknown>).date;
      if (typeof d === "string" && d.trim()) {
        tradeDay = d.trim().slice(0, 10);
        break;
      }
      if (typeof d === "number" && d > 19000101) {
        const s = String(d);
        tradeDay = `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
        break;
      }
    }
  }
  const close = typeof closeRaw === "number" ? closeRaw : (closeRaw != null ? Number(closeRaw) : null);
  const changePct = typeof chgRaw === "number" ? chgRaw : (chgRaw != null ? Number(chgRaw) : null);
  const amount = typeof amtRaw === "number" ? amtRaw : (amtRaw != null ? Number(amtRaw) : null);
  let ticker: string | null = null;
  const codeMatch = String(rawKey).match(/(\d{6})/);
  if (codeMatch) ticker = codeMatch[1];
  for (const row of NL_ASSET_ALIASES) {
    if (row.match.test(rawKey) || row.asset === rawKey) {
      ticker = row.code || ticker;
      rawKey = row.asset;
      break;
    }
  }
  return {
    assetName: String(rawKey),
    ticker,
    close: Number.isFinite(close as number) ? (close as number) : null,
    changePct: Number.isFinite(changePct as number) ? (changePct as number) : null,
    amount: Number.isFinite(amount as number) ? (amount as number) : null,
    tradeDay,
    rawAssetKey: String(rawKey),
  };
}

function buildSnapshotTable(norm: QbsSnapshotNorm): NlAnalyzeTable {
  const code = norm.ticker ? `${norm.ticker}` : "—";
  return {
    title: "关键行情字段（不复权）",
    name: "snapshot",
    columns: ["字段", "值", "说明"],
    rows: [
      ["代码", code, norm.assetName],
      ["收盘价", formatCloseDisplay(norm.close), norm.tradeDay ? `交易日 ${norm.tradeDay}` : "最近交易日"],
      ["涨跌幅", formatChangePctDisplay(norm.changePct), "较前一交易日收盘"],
      ["成交额", formatAmountDisplay(norm.amount), "当日累计"],
    ],
  };
}

function snapshotHasQuoteNumbers(norm: QbsSnapshotNorm): boolean {
  return norm.close != null || norm.changePct != null || norm.amount != null;
}

interface QbsReportMetric {
  name: string;
  valueDisplay: string;
  unit: string;
  period: string;
}

interface QbsReportNorm {
  assetName: string;
  ticker: string | null;
  metrics: QbsReportMetric[];
  reportPeriod: string | null;
  rawAssetKey: string;
}

function pickQbsAssetFields(
  data: Record<string, unknown>,
  requestedAssets: string[],
): { assetName: string; ticker: string | null; assetFields: Record<string, unknown>; rawAssetKey: string } | null {
  const payload = unwrapQbsPayload(data);
  const results = payload.results;
  if (results == null) return null;

  let assetName = requestedAssets[0] || "未知资产";
  let ticker: string | null = null;
  let assetFields: Record<string, unknown> = {};
  let rawAssetKey = assetName;

  if (Array.isArray(results)) {
    if (!results.length) return null;
    let picked: Record<string, unknown> | null = null;
    for (const want of requestedAssets) {
      const hit = results.find((row) => {
        if (!row || typeof row !== "object") return false;
        const r = row as Record<string, unknown>;
        const name = String(r.asset_name || r.asset_intent || r.name || r.asset || "");
        const tk = String(r.ticker || "");
        return name === want || name.includes(want) || want.includes(name) || tk.includes(want);
      });
      if (hit && typeof hit === "object") { picked = hit as Record<string, unknown>; break; }
    }
    if (!picked && results[0] && typeof results[0] === "object") {
      const first = results[0] as Record<string, unknown>;
      if (first.fields || first.收盘价 || first.close || first.asset || first.asset_name) {
        picked = first;
      } else {
        for (const [k, v] of Object.entries(first)) {
          if (v && typeof v === "object") {
            picked = { asset_name: k, ...(v as Record<string, unknown>) };
            rawAssetKey = k;
            break;
          }
        }
      }
    }
    if (!picked) return null;
    assetName = String(picked.asset_name || picked.asset_intent || picked.name || picked.asset || rawAssetKey || assetName);
    rawAssetKey = assetName;
    ticker = typeof picked.ticker === "string" ? picked.ticker : null;
    const codeMatch = String(rawAssetKey + " " + (ticker || "")).match(/(\d{6})/);
    if (codeMatch) ticker = ticker || codeMatch[1];
    assetFields = fieldMapFromAsset(picked);
  } else if (typeof results === "object") {
    const entries = Object.entries(results as Record<string, unknown>);
    if (!entries.length) return null;
    let picked: [string, unknown] | null = null;
    for (const want of requestedAssets) {
      const hit = entries.find(([k]) => k === want || k.includes(want) || want.includes(k));
      if (hit) { picked = hit; break; }
    }
    if (!picked) picked = entries[0];
    const [key, assetRaw] = picked;
    rawAssetKey = key;
    assetName = key || assetName;
    if (!assetRaw || typeof assetRaw !== "object") return null;
    const asset = assetRaw as Record<string, unknown>;
    ticker = typeof asset.ticker === "string" ? asset.ticker : null;
    assetFields = fieldMapFromAsset(asset);
  } else {
    return null;
  }
  return { assetName, ticker, assetFields, rawAssetKey };
}

function formatReportMetricValue(name: string, value: number | string | null, unitRaw: unknown): { display: string; unit: string } {
  const unitHint = typeof unitRaw === "string" ? unitRaw.trim() : "";
  const pctLike = /ROE|收益率|利率|资产负债率|毛利率|净利率/i.test(name) || /%|％/.test(unitHint);
  if (typeof value === "number" && Number.isFinite(value)) {
    if (pctLike) {
      let pct = value;
      if (!/%|％/.test(unitHint) && Math.abs(value) <= 1.5) pct = value * 100;
      return { display: `${pct.toFixed(2)}%`, unit: "%" };
    }
    if (/净利润|营收|收入|利润|净买额|EBITDA/i.test(name)) {
      return { display: formatAmount(value), unit: unitHint || "元" };
    }
    return { display: value.toLocaleString("zh-CN", { maximumFractionDigits: 4 }), unit: unitHint || "—" };
  }
  if (typeof value === "string" && value.trim()) {
    const t = value.trim();
    if (pctLike && !/%|％/.test(t) && Number.isFinite(Number(t))) {
      let pct = Number(t);
      if (!/%|％/.test(unitHint) && Math.abs(pct) <= 1.5) pct = pct * 100;
      return { display: `${pct.toFixed(2)}%`, unit: "%" };
    }
    return { display: t, unit: unitHint || (pctLike ? "%" : "—") };
  }
  return { display: "—", unit: unitHint || "—" };
}

function normalizeQbsReport(
  data: Record<string, unknown>,
  requestedAssets: string[],
  fields: string[],
): QbsReportNorm | null {
  const picked = pickQbsAssetFields(data, requestedAssets);
  if (!picked) return null;
  const { assetName, ticker, assetFields, rawAssetKey } = picked;

  const synonymGroups: Array<{ labels: string[]; canonical: string }> = [
    { labels: ["ROE", "净资产收益率", "加权净资产收益率"], canonical: "ROE" },
    { labels: ["净利润", "净利"], canonical: "净利润" },
    { labels: ["归母净利润", "归母净利", "归属于母公司净利润"], canonical: "归母净利润" },
    { labels: ["EBITDA", "ebitda"], canonical: "EBITDA" },
    { labels: ["龙虎榜净买额", "净买额", "龙虎榜"], canonical: "龙虎榜净买额" },
    { labels: ["GICS行业", "GICS", "所属行业", "行业"], canonical: "GICS行业" },
    { labels: ["资产负债率"], canonical: "资产负债率" },
    { labels: ["营收", "营业收入", "营业总收入"], canonical: "营收" },
  ];

  const metrics: QbsReportMetric[] = [];
  let reportPeriod: string | null = null;

  const resolveCell = (want: string): { key: string; cell: unknown } | null => {
    const group = synonymGroups.find((g) => g.canonical === want || g.labels.includes(want));
    const labels = group ? group.labels : [want];
    for (const label of labels) {
      if (label in assetFields) return { key: group?.canonical || want, cell: assetFields[label] };
    }
    for (const [k, v] of Object.entries(assetFields)) {
      if (labels.some((l) => k === l || k.includes(l) || l.includes(k))) return { key: group?.canonical || want, cell: v };
    }
    return null;
  };

  const order = fields.length ? fields : ["ROE", "净利润", "资产负债率"];
  for (const want of order) {
    const hit = resolveCell(want);
    if (!hit) {
      metrics.push({ name: want, valueDisplay: "—", unit: "—", period: "—" });
      continue;
    }
    const cell = hit.cell;
    let value: number | string | null = null;
    let unit: unknown = null;
    let period = "—";
    if (cell && typeof cell === "object" && !Array.isArray(cell)) {
      const obj = cell as Record<string, unknown>;
      value = unwrapQbsScalar(obj);
      unit = obj.unit;
      if (typeof obj.d === "string" && obj.d.trim()) period = obj.d.trim();
      else if (typeof obj.date === "string" && obj.date.trim()) period = obj.date.trim();
    } else {
      value = unwrapQbsScalar(cell);
    }
    if (period !== "—") reportPeriod = reportPeriod || period;
    const formatted = formatReportMetricValue(hit.key, value, unit);
    metrics.push({
      name: hit.key,
      valueDisplay: formatted.display,
      unit: formatted.unit,
      period,
    });
  }

  if (!metrics.length) return null;
  return { assetName, ticker, metrics, reportPeriod, rawAssetKey };
}

function buildReportTable(norm: QbsReportNorm): NlAnalyzeTable {
  return {
    title: "最近报告期关键指标",
    name: "report",
    columns: ["指标", "值", "单位", "报告期"],
    rows: norm.metrics.map((m) => [m.name, m.valueDisplay, m.unit, m.period]),
  };
}

function qbsLooksUnidentifiable(data: Record<string, unknown>): string | null {
  const blob = JSON.stringify(data);
  if (!/所有资产均无法识别|ASSETS_REQUIRED|assets\s*不能为空|MISSING_ASSET|无法识别资产/i.test(blob)) return null;
  const tryMsg = (obj: Record<string, unknown>): string | null => {
    const nested = (obj.error && typeof obj.error === "object") ? obj.error as Record<string, unknown> : null;
    const raw = nested
      ? (nested.message || nested.msg || nested.code)
      : (obj.message || obj.msg || obj.error);
    const s = String(raw || "").trim();
    return s || null;
  };
  return tryMsg(data) || tryMsg(unwrapQbsPayload(data)) || "所有资产均无法识别";
}

function isSpuriousIndexAsset(name: string, requestedAssets: string[], userQuery: string): boolean {
  if (requestedAssets.length) return false;
  if (!looksLikeSilentIndex(name)) return false;
  return !/881001|万得全A|全A/.test(userQuery);
}

function shanghaiYmdParts(date = new Date()): { y: number; m: number; d: number; iso: string; yyyymmdd: number } {
  const fmt = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" });
  const iso = fmt.format(date);
  const [ys, ms, ds] = iso.split("-");
  const y = Number(ys), m = Number(ms), d = Number(ds);
  return { y, m, d, iso, yyyymmdd: y * 10000 + m * 100 + d };
}

function mapQbsError(status: number, body: unknown): {
  code: string; message: string; http: number; retryable?: boolean; upstream?: Record<string, unknown>;
} {
  const obj = (body && typeof body === "object") ? body as Record<string, unknown> : {};
  const nestedErr = (obj.error && typeof obj.error === "object") ? obj.error as Record<string, unknown> : null;
  const msgRaw = nestedErr
    ? (nestedErr.message || nestedErr.msg || nestedErr.code || "")
    : (obj.message || obj.msg || (typeof obj.error === "string" ? obj.error : ""));
  const msg = String(msgRaw || "").trim();
  const upstreamCode = String(
    (nestedErr && (nestedErr.code || nestedErr.error_code)) ||
    obj.error_code ||
    (typeof obj.code === "string" || typeof obj.code === "number" ? obj.code : status)
  );
  if (status === 429 || /quota|rate.?limit|额度/i.test(msg) || /QUOTA|RATE_LIMIT/i.test(upstreamCode)) {
    return { code: "quota", message: msg || "上游额度不足或限流。", http: 429, retryable: true, upstream: { provider: "quantbuddy", code: upstreamCode } };
  }
  if (status === 408 || status === 504 || /timeout|超时/i.test(msg)) {
    return { code: "timeout", message: msg || "上游请求超时。", http: 504, retryable: true, upstream: { provider: "quantbuddy", code: upstreamCode } };
  }
  if (status >= 500) {
    return { code: "UPSTREAM_ERROR", message: msg || "上游服务异常。", http: 502, retryable: true, upstream: { provider: "quantbuddy", code: upstreamCode } };
  }
  return {
    code: "UPSTREAM_ERROR",
    message: msg || `上游返回 HTTP ${status}。`,
    http: 502,
    upstream: { provider: "quantbuddy", code: upstreamCode },
  };
}

async function callQbsJson(
  apiKey: string,
  url: string,
  body: Record<string, unknown>,
  timeoutMs: number,
): Promise<{ ok: true; data: Record<string, unknown>; status: number } | { ok: false; error: ReturnType<typeof mapQbsError> }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    let parsed: unknown = null;
    try { parsed = await res.json(); } catch { parsed = null; }
    if (!res.ok) {
      return { ok: false, error: mapQbsError(res.status, parsed) };
    }
    const data = (parsed && typeof parsed === "object") ? parsed as Record<string, unknown> : {};
    const payload = unwrapQbsPayload(data);
    const nestedErr = (data.error && typeof data.error === "object") ? data.error as Record<string, unknown>
      : (payload.error && typeof payload.error === "object") ? payload.error as Record<string, unknown>
      : null;
    const failed =
      data.success === false ||
      payload.success === false ||
      (typeof data.code === "number" && data.code !== 0) ||
      (typeof payload.code === "number" && payload.code !== 0 && payload.results == null && !Array.isArray((payload as Record<string, unknown>).data) && !payload.base64);
    const hasUseful =
      Array.isArray((payload as Record<string, unknown>).data) ||
      Array.isArray(payload.results) ||
      !!payload.last_column_full ||
      Array.isArray(payload.values) ||
      typeof payload.base64 === "string" ||
      !!payload.precheck ||
      !!payload.range_data ||
      !!payload.signature;
    if (failed && !hasUseful) {
      const errBody = nestedErr
        ? { ...data, ...payload, message: nestedErr.message || nestedErr.msg, error_code: nestedErr.code, code: nestedErr.code || data.code }
        : { ...data, ...payload };
      return { ok: false, error: mapQbsError(res.status || 400, errBody) };
    }
    return { ok: true, data: { ...payload, _quota: data._quota, task_id: data.task_id ?? payload.task_id, code: data.code, _raw: data }, status: res.status };
  } catch (err) {
    const aborted = err instanceof Error && err.name === "AbortError";
    return {
      ok: false,
      error: {
        code: aborted ? "timeout" : "UPSTREAM_ERROR",
        message: aborted ? "上游请求超时。" : "上游网络异常。",
        http: aborted ? 504 : 502,
        retryable: true,
        upstream: { provider: "quantbuddy", code: aborted ? "TIMEOUT" : "NETWORK" },
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

function extractQuotaRu(data: Record<string, unknown>): number | null {
  const quota = data._quota;
  if (quota && typeof quota === "object") {
    const q = quota as Record<string, unknown>;
    if (typeof q.cost === "number") return q.cost;
    if (typeof q.ru_used === "number") return q.ru_used;
    if (typeof q.used === "number") return q.used;
  }
  const raw = data._raw;
  if (raw && typeof raw === "object") {
    return extractQuotaRu(raw as Record<string, unknown>);
  }
  return null;
}

function stripDataUriBase64(raw: string): { mime: string; data_base64: string } {
  const m = raw.match(/^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/s);
  if (m) return { mime: m[1], data_base64: m[2] };
  return { mime: "image/png", data_base64: raw.replace(/^data:[^;]+;base64,/, "") };
}

/** Collect data_id from batch / confirm results (live shapes). */
function collectDataIdsFromBatch(data: Record<string, unknown>): Array<{ name: string; data_id: string }> {
  const out: Array<{ name: string; data_id: string }> = [];
  const payload = unwrapQbsPayload(data);
  const rows: unknown[] = [];
  if (Array.isArray(payload.results)) rows.push(...payload.results);
  if (Array.isArray(payload.data)) rows.push(...payload.data);
  const nested = payload.data;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    const n = nested as Record<string, unknown>;
    if (Array.isArray(n.data)) rows.push(...n.data);
    if (Array.isArray(n.results)) rows.push(...n.results);
  }
  for (const item of rows) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const indexInfo = (row.index_info && typeof row.index_info === "object")
      ? row.index_info as Record<string, unknown>
      : null;
    const name = String(row.variable_name || row.leftName || row.name || row.index_title || (indexInfo && indexInfo.index_title) || "");
    const id = row.data_id
      ?? row.indexinfo_id
      ?? (indexInfo && (indexInfo._id || indexInfo.data_id))
      ?? row._id;
    if (typeof id === "string" && id.trim()) {
      out.push({ name: name || id.trim(), data_id: id.trim() });
    }
  }
  return out;
}

function looksLikeShortQuoteQuery(query: string): boolean {
  const q = query.trim();
  if (q.length > 40) return false;
  if (/回测|筛选|全\s*A|净值|相对|排名|创新高|放量|组合|因子/i.test(q)) return false;
  const assets = extractAssetsFromQuery(q);
  if (!assets.length) return false;
  return /行情|收盘|涨跌|成交|最新|股价|报价|多少钱|什么价/.test(q) || /^[\dA-Za-z\u4e00-\u9fff\s]{2,20}$/.test(q);
}

// ─── OpenAI-compatible tool schemas for skill_direct ───

const SKILL_DIRECT_TOOLS: Array<Record<string, unknown>> = [
  {
    type: "function",
    function: {
      name: "new_session",
      description: "创建 QBS 会话并返回 task_id。后续工具调用应带上同一 task_id。",
      parameters: {
        type: "object",
        properties: {
          user_query: { type: "string", description: "用户原话" },
          agent_intent: { type: "string", description: "本轮意图简述" },
        },
        required: ["user_query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "fast_query",
      description: "单票/少票快查：snapshot 行情、window 区间、report 财报。不适用于全市场筛选或回测。",
      parameters: {
        type: "object",
        properties: {
          assets: { type: "array", items: { type: "string" }, description: "中文名或代码" },
          query_type: { type: "string", enum: ["snapshot", "window", "report"] },
          fields: { type: "array", items: { type: "string" } },
          user_query: { type: "string" },
          task_id: { type: "string" },
          window_days: { type: "number" },
        },
        required: ["assets", "query_type", "fields"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "confirm_data_multi",
      description: "写公式前确认数据名（PE/ROE/非ST 等）。data_desc 为逗号分隔字符串。",
      parameters: {
        type: "object",
        properties: {
          data_desc: { type: "string" },
          content: { type: "string" },
          dimension: { type: "string", enum: ["one-row", "two"] },
          is_bool: { type: "boolean" },
          task_id: { type: "string" },
        },
        required: ["data_desc"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "run_multi_formula",
      description: "同步执行多条公式（选股/因子/回测）。formulas 一条一个元素；引用数据名双引号；板块(万得全A)不加引号。回测须显式 begin_date（如 20150101）。force_reusable_array 列出要读的变量名。",
      parameters: {
        type: "object",
        properties: {
          formulas: { type: "array", items: { type: "string" } },
          begin_date: { type: "number" },
          force_reusable_array: { type: "array", items: { type: "string" } },
          use_minute_data: { type: "boolean" },
          user_query: { type: "string" },
          task_id: { type: "string" },
          execution_profile: { type: "string" },
          output_mode: { type: "string" },
        },
        required: ["formulas", "begin_date"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_data",
      description: "读取计算结果。ids 必须是 data_id（index_info._id），禁止 expression_id / 中文变量名。mode: precheck|last_column_full|range_data|smart_sample|signature 等。",
      parameters: {
        type: "object",
        properties: {
          ids: { type: "array", items: { type: "string" } },
          mode: { type: "string" },
          task_id: { type: "string" },
          start_date: { type: "number" },
          end_date: { type: "number" },
          max_rows: { type: "number" },
          top_assets: { type: "number" },
          decimal_places: { type: "number" },
        },
        required: ["ids"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "render_chart",
      description: "渲染折线/柱状等图表，返回 PNG base64。lines[].id 为 data_id。",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string" },
          chart_type: { type: "string", enum: ["line", "bar", "area"] },
          lines: {
            type: "array",
            items: {
              type: "object",
              properties: {
                id: { type: "string" },
                name: { type: "string" },
                axis: { type: "string" },
              },
              required: ["id", "name"],
            },
          },
          start_date: { type: "number" },
          task_id: { type: "string" },
          width: { type: "number" },
          height: { type: "number" },
        },
        required: ["lines"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "render_kline",
      description: "单票 K 线 PNG。ticker 如 SH600519 / SZ300750。",
      parameters: {
        type: "object",
        properties: {
          ticker: { type: "string" },
          begin_date: { type: "number" },
          task_id: { type: "string" },
          title: { type: "string" },
        },
        required: ["ticker", "begin_date"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "finish_report",
      description: "结束工具环并提交最终报告。在已有足够工具结果后调用。",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string" },
          summary_md: { type: "string" },
          sections: {
            type: "array",
            items: {
              type: "object",
              properties: {
                heading: { type: "string" },
                body_md: { type: "string" },
              },
              required: ["heading", "body_md"],
            },
          },
        },
        required: ["title", "summary_md"],
      },
    },
  },
];

function skillDirectSystemPrompt(userQuery: string): string {
  return [
    "你是巴小卡 nl-analyze 的 Quant Buddy 技能直调 Agent（skill_direct）。",
    "通过 function calling 调用工具完成用户问题，最后用 finish_report 提交中文结论。",
    "禁止意图分类器思维；不要只返回 intent=quote|screen|report。",
    "",
    "硬规则：",
    "1) formulas 数组一条公式一个元素；引用数据名用双引号；板块(万得全A)名不加引号。",
    "2) read_data.ids 只用 data_id（来自 run_multi_formula / confirm 的 index_info._id），禁用 expression_id 与中文变量名。",
    "3) 回测/长历史：begin_date 显式（含回测( 用 20150101 或 20210101）；force_reusable_array 保活要读的变量。",
    "4) 先 new_session 拿 task_id，后续工具带同一 task_id。",
    "5) 用户原话必须作为 user_query 传入相关工具（尤其 fast_query）。",
    "6) 最多约 8 步；优先 sync run_multi_formula。",
    "7) 单票/字段快查用 fast_query；全市场筛选/回测用 confirm → run_multi_formula → read_data →（可选）render_chart。",
    "8) 严禁客服式追问。禁止最终回答「请提供股票名称/代码」「查询标的待确认」等澄清话术。",
    "9) 即便问句未写清 ticker：仍须调用 fast_query，query_type=report（或 snapshot），fields 从问句抽取，user_query=用户原话 verbatim；无 6 位代码且无已知公司名时 assets=[]（禁止把归母净利润/EBITDA/龙虎榜/GICS 等指标名当 assets，禁止擅自换成 881001/万得全A/CSI）。若上游「所有资产均无法识别」等，把上游错误原样交给 finish_report，禁止澄清话术。",
    "10) finish_report 前必须至少成功一次数据工具：fast_query，或 run_multi_formula（并可 read_data）。仅 new_session 不够。",
    "",
    "回测低PE+高ROE相对沪深300 few-shot（可改写，口径须含低PE∩高ROE、等权回测、沪深300）：",
    JSON.stringify(BACKTEST_FEWSHOT),
    "",
    "全A放量突破 TopN 公式仅作示例（不是唯一路径）：",
    JSON.stringify(SCREEN_FEWSHOT_FORMULAS),
    "",
    `当前用户问句：${userQuery}`,
  ].join("\n");
}

interface SkillAgentState {
  taskId: string | null;
  ruUsed: number;
  toolTrace: NlAnalyzeToolTrace[];
  charts: NlAnalyzeChart[];
  tables: NlAnalyzeTable[];
  series: NlAnalyzeSeries[];
  kpis?: NlAnalyzeKpis;
  sources: NlAnalyzeSource[];
  asOf: string | null;
  batchIds: Array<{ name: string; data_id: string }>;
  lastFastNorm: QbsSnapshotNorm | null;
  lastReportNorm: QbsReportNorm | null;
  lastDataError?: { code: string; message: string; tool: string };
  finish?: { title: string; summary_md: string; sections: NlAnalyzeSection[] };
}


function looksLikeClarificationText(text: string): boolean {
  return /请提供|股票名称或代码|查询标的待确认|标的待确认|请补充.{0,12}(代码|名称|股票)|请先告知|需要知道.*(股票|代码)/.test(text);
}

function hasSuccessfulDataTool(state: SkillAgentState): boolean {
  return state.toolTrace.some((t) => t.ok && (t.tool === "fast_query" || t.tool === "run_multi_formula" || t.tool === "read_data"));
}

function isMetricOnlyQuery(query: string): boolean {
  if (extractAssetsFromQuery(query).length) return false;
  if (/回测|筛选|放量|创新高|全A股|相对沪深|净值/.test(query)) return false;
  return /归母|EBITDA|龙虎榜|GICS|ROE|净利润|资产负债|营收|财报|报告期|所属行业/i.test(query);
}

function fieldsFromUserQuery(query: string): string[] {
  const wanted: string[] = [];
  const push = (f: string) => { if (!wanted.includes(f)) wanted.push(f); };
  if (/归母/.test(query)) push("归母净利润");
  if (/EBITDA|ebitda/i.test(query)) push("EBITDA");
  if (/龙虎榜|净买额/.test(query)) push("龙虎榜净买额");
  if (/GICS/i.test(query)) push("GICS行业");
  else if (/所属行业|行业/.test(query)) push("所属行业");
  if (/ROE|净资产收益率/i.test(query)) push("ROE");
  if (/净利润/.test(query) && !/归母/.test(query)) push("净利润");
  if (/资产负债率/.test(query)) push("资产负债率");
  if (/营收|营业收入/.test(query)) push("营业收入");
  if (/收盘|涨跌|成交额/.test(query) && !/归母|EBITDA|龙虎榜|GICS|行业|ROE|财报/.test(query)) {
    push("收盘价"); push("涨跌幅"); push("成交额");
  }
  if (!wanted.length) {
    push("ROE"); push("净利润"); push("资产负债率");
  }
  return wanted;
}

function inferFastQueryType(query: string, fields: string[]): "snapshot" | "window" | "report" {
  if (/收盘|涨跌|成交额|行情|股价/.test(query) && !/归母|EBITDA|ROE|财报|报告期|龙虎榜|GICS|行业/.test(query)) {
    return "snapshot";
  }
  if (fields.some((f) => /收盘|涨跌|成交/.test(f)) && fields.every((f) => /收盘|涨跌|成交|开盘|最高|最低/.test(f))) {
    return "snapshot";
  }
  return "report";
}

async function executeSkillTool(
  apiKey: string,
  name: string,
  args: Record<string, unknown>,
  state: SkillAgentState,
  userQuery: string,
  deadline: number,
): Promise<{ content: string; ok: boolean }> {
  const remain = Math.max(5_000, deadline - Date.now());
  const defaultMs = (SKILL_DIRECT_TOOL_MS as Record<string, number>)[name] || 60_000;
  const timeoutMs = Math.min(defaultMs, remain);
  const t0 = Date.now();

  const withTask = (body: Record<string, unknown>) => {
    const tid = (typeof args.task_id === "string" && args.task_id.trim()) || state.taskId;
    if (tid) body.task_id = tid;
    return body;
  };

  try {
    if (name === "new_session") {
      const taskId = newTaskId();
      const turnId = newTaskId();
      const body = {
        task_id: taskId,
        turn_id: turnId,
        user_query: String(args.user_query || userQuery),
        agent_intent: typeof args.agent_intent === "string" ? args.agent_intent : undefined,
      };
      const res = await callQbsJson(apiKey, QBS_SESSION_BEGIN_URL, body, timeoutMs);
      state.taskId = taskId;
      if (res.ok) {
        const ru = extractQuotaRu(res.data);
        if (ru != null) state.ruUsed += ru;
        if (typeof res.data.task_id === "string" && res.data.task_id) state.taskId = res.data.task_id;
      }
      // session begin failure is soft — keep client UUID
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: true, ms: Date.now() - t0, detail: `task_id=${state.taskId}` });
      state.sources.push({ name: "Quant Buddy new_session", provider: "quantbuddy", tool: "new_session", task_id: state.taskId || undefined, endpoint: "POST /skill/session/begin" });
      return { ok: true, content: JSON.stringify({ task_id: state.taskId, note: res.ok ? "session ok" : "local task_id (session soft-fail)" }) };
    }

    if (name === "fast_query") {
      const rawAssets = Array.isArray(args.assets) ? args.assets.map((a) => String(a).trim()).filter(Boolean) : [];
      const queryType = String(args.query_type || "snapshot") as "snapshot" | "window" | "report";
      const parsedFields = fieldsFromUserQuery(userQuery);
      const fields = Array.isArray(args.fields) && args.fields.length
        ? args.fields.map((f) => String(f))
        : (queryType === "snapshot" ? [...QBS_SNAPSHOT_FIELDS] : parsedFields);
      // Never treat metric names / silent index as assets; empty is OK — pass verbatim user_query.
      const resolvedAssets = sanitizeAssetList(rawAssets.length ? rawAssets : extractAssetsFromQuery(userQuery));
      const effectiveFields = fields.length ? fields : (queryType === "report" ? parsedFields : [...QBS_SNAPSHOT_FIELDS]);
      const body = withTask({
        assets: resolvedAssets,
        query_type: queryType,
        fields: effectiveFields,
        user_query: String(args.user_query || userQuery),
      });
      if (typeof args.window_days === "number") body.window_days = args.window_days;
      const res = await callQbsJson(apiKey, QBS_FAST_QUERY_URL, body, timeoutMs);
      if (!res.ok) {
        state.lastDataError = { code: res.error.code, message: res.error.message, tool: name };
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: res.error.message });
        return { ok: false, content: JSON.stringify({ error: { code: res.error.code, message: res.error.message, upstream: res.error.upstream } }) };
      }
      const unident = qbsLooksUnidentifiable(res.data);
      if (unident) {
        state.lastDataError = { code: "UPSTREAM_ERROR", message: unident, tool: name };
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: unident });
        return { ok: false, content: JSON.stringify({ error: { code: "UPSTREAM_ERROR", message: unident } }) };
      }
      const ru = extractQuotaRu(res.data);
      if (ru != null) state.ruUsed += ru;

      const wantReport = queryType === "report" || effectiveFields.some((f) => /归母|EBITDA|ROE|龙虎榜|GICS|行业|净利润|资产负债|营收|财报/i.test(f));
      let pushedUseful = false;
      if (wantReport) {
        const reportNorm = normalizeQbsReport(res.data, resolvedAssets, effectiveFields);
        if (reportNorm && !isSpuriousIndexAsset(reportNorm.rawAssetKey + reportNorm.assetName, resolvedAssets, userQuery)) {
          const hasAny = reportNorm.metrics.some((m) => m.valueDisplay !== "—");
          if (hasAny || resolvedAssets.length === 0) {
            state.lastReportNorm = reportNorm;
            state.asOf = reportNorm.reportPeriod || state.asOf;
            // Drop any empty quote tables previously pushed this turn
            state.tables = state.tables.filter((t) => t.name !== "snapshot" || (t.rows || []).some((r) => r.slice(1).some((c) => c != null && String(c) !== "—")));
            state.tables.push(buildReportTable(reportNorm));
            pushedUseful = hasAny;
          }
        }
      }

      const norm = normalizeQbsSnapshot(res.data, resolvedAssets);
      if (norm && !isSpuriousIndexAsset(norm.rawAssetKey + norm.assetName, resolvedAssets, userQuery)) {
        if (snapshotHasQuoteNumbers(norm)) {
          state.lastFastNorm = norm;
          state.asOf = norm.tradeDay || state.asOf;
          if (!wantReport || !pushedUseful) {
            state.tables.push(buildSnapshotTable(norm));
          }
          state.kpis = {
            close: formatCloseDisplay(norm.close),
            change_pct: typeof norm.changePct === "number" ? norm.changePct : undefined,
            change: formatChangePctDisplay(norm.changePct),
            amount: formatAmountDisplay(norm.amount),
          };
          pushedUseful = true;
        }
        // Empty quote cards (close/chg/amount all —) are never drawn.
      }

      state.toolTrace.push({
        step: state.toolTrace.length + 1,
        tool: name,
        ok: true,
        ms: Date.now() - t0,
        detail: `assets=${resolvedAssets.length ? resolvedAssets.join(",") : "[]"} type=${queryType}`,
      });
      state.sources.push({ name: "Quant Buddy fast_query", provider: "quantbuddy", tool: "fast_query", endpoint: "POST /skill/fastQuery", task_id: state.taskId || undefined });
      const slim = JSON.stringify(res.data).slice(0, 8000);
      return { ok: true, content: slim };
    }

    if (name === "confirm_data_multi") {
      if (isMetricOnlyQuery(userQuery)) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: "metric_only_use_fast_query" });
        return {
          ok: false,
          content: JSON.stringify({
            error: "METRIC_ONLY: 请改用 fast_query，assets=[]，query_type=report，fields 从问句抽取，user_query=原话。禁止 confirm / 万得全A / 881001。",
          }),
        };
      }
      const body = withTask({
        data_desc: String(args.data_desc || ""),
        content: typeof args.content === "string" ? args.content : userQuery,
      });
      if (typeof args.dimension === "string") body.dimension = args.dimension;
      if (typeof args.is_bool === "boolean") body.is_bool = args.is_bool;
      const res = await callQbsJson(apiKey, QBS_CONFIRM_MULTI_URL, body, timeoutMs);
      if (!res.ok) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: res.error.message });
        return { ok: false, content: JSON.stringify({ error: res.error }) };
      }
      const ru = extractQuotaRu(res.data);
      if (ru != null) state.ruUsed += ru;
      const ids = collectDataIdsFromBatch(res.data);
      if (ids.length) state.batchIds.push(...ids);
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: true, ms: Date.now() - t0, detail: `matched=${ids.length}` });
      state.sources.push({ name: "Quant Buddy confirm_data_multi", provider: "quantbuddy", tool: "confirm_data_multi", task_id: state.taskId || undefined });
      return { ok: true, content: JSON.stringify(res.data).slice(0, 8000) };
    }

    if (name === "run_multi_formula") {
      if (isMetricOnlyQuery(userQuery)) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: "metric_only_use_fast_query" });
        return {
          ok: false,
          content: JSON.stringify({
            error: "METRIC_ONLY: 请改用 fast_query，assets=[]，query_type=report，fields 从问句抽取。禁止 run_multi_formula / 万得全A。",
          }),
        };
      }
      const formulas = Array.isArray(args.formulas) ? args.formulas.map((f) => String(f)) : [];
      if (!formulas.length) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, detail: "empty formulas" });
        return { ok: false, content: JSON.stringify({ error: "formulas required" }) };
      }
      if (!state.taskId) state.taskId = newTaskId();
      const body = withTask({
        formulas,
        begin_date: typeof args.begin_date === "number" ? args.begin_date : 20150101,
        user_query: String(args.user_query || userQuery),
        output_mode: typeof args.output_mode === "string" ? args.output_mode : "summary",
      });
      if (Array.isArray(args.force_reusable_array)) body.force_reusable_array = args.force_reusable_array;
      if (typeof args.use_minute_data === "boolean") body.use_minute_data = args.use_minute_data;
      if (typeof args.execution_profile === "string") body.execution_profile = args.execution_profile;
      const res = await callQbsJson(apiKey, QBS_RUN_MULTI_URL, body, timeoutMs);
      if (!res.ok) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: res.error.message });
        return { ok: false, content: JSON.stringify({ error: res.error }) };
      }
      const ru = extractQuotaRu(res.data);
      if (ru != null) state.ruUsed += ru;
      if (typeof res.data.task_id === "string" && res.data.task_id) state.taskId = res.data.task_id;
      const ids = collectDataIdsFromBatch(res.data);
      state.batchIds = ids.length ? ids : state.batchIds;
      // compact id map for LLM
      const idMap = Object.fromEntries(ids.map((x) => [x.name, x.data_id]));
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: true, ms: Date.now() - t0, detail: `vars=${ids.length}` });
      state.sources.push({ name: "Quant Buddy run_multi_formula", provider: "quantbuddy", tool: "run_multi_formula", endpoint: "POST /skill/runMultiFormulaBatch", task_id: state.taskId || undefined });
      return { ok: true, content: JSON.stringify({ task_id: state.taskId, data_ids: idMap, hint: "use data_ids values in read_data.ids / render_chart.lines[].id" }).slice(0, 8000) };
    }

    if (name === "read_data") {
      let ids = Array.isArray(args.ids) ? args.ids.map((x) => String(x).trim()).filter(Boolean) : [];
      // Resolve variable names → data_id if model passed names by mistake
      ids = ids.map((id) => {
        if (/^[a-f0-9]{24}$/i.test(id)) return id;
        const hit = state.batchIds.find((b) => b.name === id || b.name.toLowerCase() === id.toLowerCase());
        return hit ? hit.data_id : id;
      });
      const mode = typeof args.mode === "string" ? args.mode : "precheck";
      const body = withTask({
        ids,
        mode,
        decimal_places: typeof args.decimal_places === "number" ? args.decimal_places : 4,
      });
      if (typeof args.start_date === "number") body.start_date = args.start_date;
      if (typeof args.end_date === "number") body.end_date = args.end_date;
      if (typeof args.max_rows === "number") body.max_rows = args.max_rows;
      if (typeof args.top_assets === "number") body.top_assets = args.top_assets;
      if (mode === "last_column_full" && body.max_rows == null) body.max_rows = 50;
      const res = await callQbsJson(apiKey, QBS_READ_DATA_URL, body, timeoutMs);
      if (!res.ok) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: res.error.message });
        return { ok: false, content: JSON.stringify({ error: res.error }) };
      }
      const ru = extractQuotaRu(res.data);
      if (ru != null) state.ruUsed += ru;
      harvestReadArtifacts(res.data, state, mode);
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: true, ms: Date.now() - t0, detail: mode });
      state.sources.push({ name: "Quant Buddy read_data", provider: "quantbuddy", tool: "read_data", task_id: state.taskId || undefined });
      return { ok: true, content: JSON.stringify(res.data).slice(0, 10000) };
    }

    if (name === "render_chart") {
      const lines = Array.isArray(args.lines) ? args.lines : [];
      const resolved = lines.map((ln) => {
        const row = (ln && typeof ln === "object") ? ln as Record<string, unknown> : {};
        let id = String(row.id || "");
        if (id && !/^[a-f0-9]{24}$/i.test(id)) {
          const hit = state.batchIds.find((b) => b.name === id);
          if (hit) id = hit.data_id;
        }
        return { id, name: String(row.name || id), axis: row.axis ? String(row.axis) : undefined };
      }).filter((l) => l.id);
      const body = withTask({
        title: typeof args.title === "string" ? args.title : "图表",
        chart_type: typeof args.chart_type === "string" ? args.chart_type : "line",
        lines: resolved,
      });
      if (typeof args.start_date === "number") body.start_date = args.start_date;
      if (typeof args.width === "number") body.width = args.width;
      if (typeof args.height === "number") body.height = args.height;
      const res = await callQbsJson(apiKey, QBS_RENDER_CHART_URL, body, timeoutMs);
      if (!res.ok) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: res.error.message });
        return { ok: false, content: JSON.stringify({ error: res.error }) };
      }
      const ru = extractQuotaRu(res.data);
      if (ru != null) state.ruUsed += ru;
      const b64raw = typeof res.data.base64 === "string" ? res.data.base64
        : (typeof (res.data as Record<string, unknown>).image_base64 === "string" ? String((res.data as Record<string, unknown>).image_base64) : "");
      if (b64raw) {
        const stripped = stripDataUriBase64(b64raw);
        state.charts.push({
          name: String(args.title || "图表"),
          mime: stripped.mime,
          data_base64: stripped.data_base64,
          url: null,
        });
      }
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: !!b64raw, ms: Date.now() - t0 });
      state.sources.push({ name: "Quant Buddy render_chart", provider: "quantbuddy", tool: "render_chart", task_id: state.taskId || undefined });
      return { ok: true, content: JSON.stringify({ chart_ok: !!b64raw, lines_count: resolved.length, mime: "image/png" }) };
    }

    if (name === "render_kline") {
      const body = withTask({
        ticker: String(args.ticker || ""),
        begin_date: typeof args.begin_date === "number" ? args.begin_date : 20210101,
        title: typeof args.title === "string" ? args.title : undefined,
      });
      const res = await callQbsJson(apiKey, QBS_RENDER_KLINE_URL, body, timeoutMs);
      if (!res.ok) {
        state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: res.error.message });
        return { ok: false, content: JSON.stringify({ error: res.error }) };
      }
      const b64raw = typeof res.data.base64 === "string" ? res.data.base64 : "";
      if (b64raw) {
        const stripped = stripDataUriBase64(b64raw);
        state.charts.push({ name: String(args.title || args.ticker || "K线"), mime: stripped.mime, data_base64: stripped.data_base64, url: null });
      }
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: !!b64raw, ms: Date.now() - t0 });
      return { ok: true, content: JSON.stringify({ chart_ok: !!b64raw }) };
    }

    if (name === "finish_report") {
      const draftTitle = String(args.title || "智能分析");
      const draftSummary = String(args.summary_md || "");
      const draftSections = Array.isArray(args.sections)
        ? args.sections.map((s) => {
            const row = (s && typeof s === "object") ? s as Record<string, unknown> : {};
            return { heading: String(row.heading || "要点"), body_md: String(row.body_md || "") };
          })
        : [];
      const clarify = looksLikeClarificationText(draftTitle + "\n" + draftSummary + "\n" + draftSections.map((s) => s.body_md).join("\n"));
      if (!hasSuccessfulDataTool(state) || clarify) {
        state.toolTrace.push({
          step: state.toolTrace.length + 1,
          tool: name,
          ok: false,
          ms: Date.now() - t0,
          detail: clarify ? "rejected_clarification" : "need_data_tool",
        });
        return {
          ok: false,
          content: JSON.stringify({
            error: clarify
              ? "FORBIDDEN_CLARIFICATION: 禁止请用户补充代码/名称。立刻调用 fast_query，user_query=原话，fields 从问句抽取。"
              : "NEED_DATA_TOOL: finish_report 前必须至少成功一次 fast_query 或 run_multi_formula/read_data。仅 new_session 不够。",
            rejected: true,
          }),
        };
      }
      state.finish = { title: draftTitle, summary_md: draftSummary, sections: draftSections };
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: true, ms: Date.now() - t0 });
      return { ok: true, content: JSON.stringify({ finished: true }) };
    }

    state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, detail: "unknown tool" });
    return { ok: false, content: JSON.stringify({ error: `unknown tool ${name}` }) };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    state.toolTrace.push({ step: state.toolTrace.length + 1, tool: name, ok: false, ms: Date.now() - t0, detail: msg });
    return { ok: false, content: JSON.stringify({ error: msg }) };
  }
}

function harvestReadArtifacts(data: Record<string, unknown>, state: SkillAgentState, mode: string): void {
  const payload = unwrapQbsPayload(data);
  // precheck: first/last/total_return style
  const blocks: Record<string, unknown>[] = [];
  const push = (x: unknown) => {
    if (x && typeof x === "object" && !Array.isArray(x)) blocks.push(x as Record<string, unknown>);
  };
  push(payload);
  if (Array.isArray(payload.data)) {
    for (const item of payload.data) push(item);
  } else {
    push(payload.data);
  }
  if (Array.isArray(payload.results)) for (const item of payload.results) push(item);

  const metricRows: Array<Array<string | number | null>> = [];
  for (const b of blocks) {
    const pre = (b.precheck && typeof b.precheck === "object") ? b.precheck as Record<string, unknown> : b;
    const id = String(b.id || b.data_id || pre.id || "");
    const nameHit = state.batchIds.find((x) => x.data_id === id);
    const label = nameHit?.name || id.slice(0, 8) || "series";
    const first = pre.first ?? pre.first_value ?? pre.start;
    const last = pre.last ?? pre.last_value ?? pre.end;
    const tr = pre.total_return ?? pre.return ?? pre.cum_return;
    if (first != null || last != null || tr != null) {
      metricRows.push([
        label,
        first != null ? Number(first) : null,
        last != null ? Number(last) : null,
        tr != null ? (typeof tr === "number" ? `${(Math.abs(tr) <= 3 ? tr * 100 : tr).toFixed(2)}%` : String(tr)) : null,
      ]);
    }
    // range_data / last_column one-dim series
    const rd = (b.range_data && typeof b.range_data === "object") ? b.range_data as Record<string, unknown>
      : (b.last_column_full && typeof b.last_column_full === "object") ? b.last_column_full as Record<string, unknown>
      : null;
    if (rd && Array.isArray(rd.dates) && Array.isArray(rd.values) && !Array.isArray(rd.values[0])) {
      state.series.push({
        name: label,
        dates: rd.dates as Array<string | number>,
        values: (rd.values as unknown[]).map((v) => (typeof v === "number" ? v : (v == null ? null : Number(v)))),
      });
    }
    // last_column_full 2d top assets → table
    if (mode === "last_column_full" || mode === "smart_sample") {
      const block = (b.last_column_full && typeof b.last_column_full === "object")
        ? b.last_column_full as Record<string, unknown>
        : b;
      const values = block.values;
      if (Array.isArray(values) && values.length && typeof values[0] === "object") {
        const rows: Array<Array<string | number | null>> = [];
        let rank = 1;
        for (const item of values.slice(0, 30)) {
          if (!item || typeof item !== "object") continue;
          const row = item as Record<string, unknown>;
          const code = String(row.asset ?? row.code ?? row.ticker ?? "").replace(/\.(SH|SZ|BJ)$/i, "");
          const nm = String(row.name ?? row.asset_name ?? "");
          const v = row.value ?? row.v;
          rows.push([rank++, code, nm, typeof v === "number" ? v : String(v ?? "")]);
        }
        if (rows.length) {
          state.tables.push({
            name: "topn",
            title: label || "截面结果",
            columns: ["#", "代码", "名称", "值"],
            rows,
          });
        }
      }
    }
  }
  if (metricRows.length) {
    state.tables.push({
      name: "nav_metrics",
      title: "净值/收益指标",
      columns: ["序列", "起点", "终点", "累计收益"],
      rows: metricRows,
    });
  }
}

async function llmChatTools(
  env: Env,
  messages: Array<Record<string, unknown>>,
  timeoutMs: number,
): Promise<{ ok: true; message: Record<string, unknown>; model: string } | { ok: false; error: string }> {
  const cfg = resolveLlmConfig(env);
  if (!cfg.apiKey || !cfg.baseUrl) return { ok: false, error: "LLM not configured" };
  const model = cfg.model || "deepseek-chat";
  const endpoint = `${cfg.baseUrl}/chat/completions`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${cfg.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        temperature: 0.2,
        messages,
        tools: SKILL_DIRECT_TOOLS,
        tool_choice: "auto",
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const t = await res.text().catch(() => "");
      return { ok: false, error: `LLM HTTP ${res.status}: ${t.slice(0, 200)}` };
    }
    const data = await res.json() as Record<string, unknown>;
    const choices = Array.isArray(data.choices) ? data.choices : [];
    const msg = choices[0] && typeof choices[0] === "object"
      ? ((choices[0] as Record<string, unknown>).message as Record<string, unknown> | undefined)
      : undefined;
    if (!msg) return { ok: false, error: "empty LLM message" };
    return { ok: true, message: msg, model };
  } catch (err) {
    const aborted = err instanceof Error && err.name === "AbortError";
    return { ok: false, error: aborted ? "LLM timeout" : (err instanceof Error ? err.message : String(err)) };
  } finally {
    clearTimeout(timer);
  }
}

function isEmptySnapshotTable(t: NlAnalyzeTable): boolean {
  if (t.name !== "snapshot" && !/行情/.test(t.title || "")) return false;
  const rows = t.rows || [];
  // quote three-col: 收盘价/涨跌幅/成交额 all —
  const vals = rows.filter((r) => /收盘|涨跌|成交/.test(String(r[0] ?? ""))).map((r) => String(r[1] ?? "").trim());
  if (!vals.length) return false;
  return vals.every((v) => !v || v === "—" || v === "-" || v === "null");
}

function synthesizeReportFromState(query: string, state: SkillAgentState, latency_ms: number): NlAnalyzeReport {
  const finish = state.finish;
  let title = finish?.title || "智能分析";
  let summary = finish?.summary_md || "";
  const sections = finish?.sections?.length ? finish.sections : [];

  if (state.lastReportNorm) {
    const n = state.lastReportNorm;
    const label = n.ticker ? `${n.assetName}（${n.ticker}）` : (n.assetName && n.assetName !== "未知资产" ? n.assetName : "指标快查");
    const bits = n.metrics.filter((m) => m.valueDisplay !== "—").map((m) => `${m.name} ${m.valueDisplay}`).slice(0, 4);
    if (!finish) title = bits.length ? `${label} · 指标` : "指标快查";
    if (!summary) {
      summary = bits.length
        ? `报告期 ${n.reportPeriod || "最近报告期"}：${bits.join("，")}。`
        : `已按问句抽取字段查询；部分指标上游未返回数值。`;
    }
  }

  if (state.lastFastNorm && snapshotHasQuoteNumbers(state.lastFastNorm)) {
    const n = state.lastFastNorm;
    const label = n.ticker ? `${n.assetName}（${n.ticker}）` : n.assetName;
    if (!finish && !state.lastReportNorm) title = `${label}行情观察`;
    if (!summary) {
      summary = `截至 ${n.tradeDay || "最近交易日"}，${label} 收盘 ${formatCloseDisplay(n.close)}，涨跌幅 ${formatChangePctDisplay(n.changePct)}，成交额 ${formatAmountDisplay(n.amount)}。`;
    }
  }

  if (!summary && state.tables.some((t) => t.name === "nav_metrics")) {
    const t = state.tables.find((x) => x.name === "nav_metrics")!;
    const bits = t.rows.map((r) => `${r[0]} 累计 ${r[3] ?? "—"}`).join("；");
    summary = `回测/净值结果摘要：${bits || "已完成计算"}。详见下方表格与图表。`;
    if (!finish) title = "组合回测 · 净值对比";
  }

  if (!summary && state.tables.some((t) => t.name === "topn")) {
    const t = state.tables.find((x) => x.name === "topn")!;
    summary = `筛选得到 ${t.rows.length} 条截面结果（非固定放量突破模板，由 Agent 公式驱动）。`;
    if (!finish) title = "市场筛选结果";
  }

  if (!summary) {
    const okTools = state.toolTrace.filter((t) => t.ok).map((t) => t.tool).join(" → ");
    summary = okTools
      ? `已执行工具链：${okTools}。部分步骤可能未产出完整可视化，请参考表格与追踪。`
      : `未能完成分析：「${query.slice(0, 80)}」。`;
  }

  // Deduplicate + never keep empty quote cards
  const seen = new Set<string>();
  const tables: NlAnalyzeTable[] = [];
  for (const t of state.tables) {
    if (isEmptySnapshotTable(t)) continue;
    const key = `${t.name || ""}|${t.title || ""}|${t.rows.length}`;
    if (seen.has(key)) continue;
    seen.add(key);
    tables.push(t);
  }

  return {
    title,
    summary_md: summary,
    trade_day: state.asOf || undefined,
    kpis: state.kpis,
    sections: sections.length ? sections : [{ heading: "说明", body_md: "结果由 Quant Buddy 技能直调生成；仅供观察。" }],
    tables,
    series: state.series.length ? state.series : undefined,
    charts: state.charts.length ? state.charts : undefined,
    sources: state.sources.length ? state.sources : [{ name: "Quant Buddy", provider: "quantbuddy" }],
    tool_trace: state.toolTrace,
    disclaimer: NL_ANALYZE_DISCLAIMER,
    latency_ms,
    risk_lines: [...NL_ANALYZE_RISK_LINES],
  };
}

async function tryHeuristicFastQuote(
  apiKey: string,
  query: string,
  assetsIn: string[] | undefined,
  started: number,
): Promise<NlAnalyzeResponse | null> {
  if (!looksLikeShortQuoteQuery(query)) return null;
  const assets = extractAssetsFromQuery(query, assetsIn);
  if (!assets.length) return null;
  const res = await callQbsJson(apiKey, QBS_FAST_QUERY_URL, {
    assets,
    query_type: "snapshot",
    fields: [...QBS_SNAPSHOT_FIELDS],
    user_query: query,
  }, 25_000);
  if (!res.ok) return null;
  const norm = normalizeQbsSnapshot(res.data, assets);
  if (!norm || (norm.close == null && norm.changePct == null && norm.amount == null)) return null;
  const label = norm.ticker ? `${norm.assetName}（${norm.ticker}）` : displayAssetLabel(norm.assetName);
  const latency_ms = Math.max(0, Date.now() - started);
  return {
    ok: true,
    report: {
      title: `${label}行情观察`,
      summary_md: `截至 ${norm.tradeDay || "最近交易日"}，${label} 收盘 ${formatCloseDisplay(norm.close)}，涨跌幅 ${formatChangePctDisplay(norm.changePct)}，成交额 ${formatAmountDisplay(norm.amount)}。`,
      trade_day: norm.tradeDay || undefined,
      kpis: {
        close: formatCloseDisplay(norm.close),
        change_pct: typeof norm.changePct === "number" ? norm.changePct : undefined,
        change: formatChangePctDisplay(norm.changePct),
        amount: formatAmountDisplay(norm.amount),
      },
      sections: [{ heading: "行情要点", body_md: "- 快查路径（启发式加速）；完整 Agent 环仍可用于复杂问句。\n- 价格按不复权行情。" }],
      tables: [buildSnapshotTable(norm)],
      sources: [{ name: "Quant Buddy / fast_query", provider: "quantbuddy", tool: "fast_query", endpoint: "POST /skill/fastQuery" }],
      tool_trace: [{ step: 1, tool: "fast_query", ok: true, detail: "heuristic" }],
      disclaimer: NL_ANALYZE_DISCLAIMER,
      latency_ms,
      risk_lines: [...NL_ANALYZE_RISK_LINES],
    },
    meta: {
      mode: "skill_direct",
      model: null,
      steps: 1,
      ru_used: extractQuotaRu(res.data),
      as_of: norm.tradeDay,
      heuristic: "fast_quote",
    },
  };
}

async function runSkillDirectAgent(
  env: Env,
  apiKey: string,
  query: string,
  started: number,
): Promise<Response> {
  const deadline = started + SKILL_DIRECT_TOTAL_MS;
  const state: SkillAgentState = {
    taskId: null,
    ruUsed: 0,
    toolTrace: [],
    charts: [],
    tables: [],
    series: [],
    sources: [],
    asOf: null,
    batchIds: [],
    lastFastNorm: null,
    lastReportNorm: null,
  };

  const cfg = resolveLlmConfig(env);
  if (!cfg.apiKey || !cfg.baseUrl) {
    // No LLM: still try heuristic quote; else honest error (no intent no_match for screen)
    const latency_ms = Math.max(0, Date.now() - started);
    return json({
      ok: false,
      error: { code: "UPSTREAM_ERROR", message: "服务端未配置 LLM，无法运行 skill_direct Agent 环。", retryable: false },
      meta: { mode: "skill_direct", steps: 0, latency_ms },
    } satisfies NlAnalyzeResponse, 503, NL_ANALYZE_HEADERS);
  }

  const messages: Array<Record<string, unknown>> = [
    { role: "system", content: skillDirectSystemPrompt(query) },
    { role: "user", content: query },
  ];

  let modelUsed = cfg.model || "deepseek-chat";
  let steps = 0;

  for (let i = 0; i < SKILL_DIRECT_MAX_STEPS; i++) {
    if (Date.now() >= deadline) break;
    steps = i + 1;
    const llmTimeout = Math.min(45_000, Math.max(8_000, deadline - Date.now()));
    const turn = await llmChatTools(env, messages, llmTimeout);
    if (!turn.ok) {
      state.toolTrace.push({ step: state.toolTrace.length + 1, tool: "llm", ok: false, detail: turn.error });
      break;
    }
    modelUsed = turn.model;
    const msg = turn.message;
    messages.push(msg);

    const toolCalls = Array.isArray(msg.tool_calls) ? msg.tool_calls : [];
    if (!toolCalls.length) {
      const content = typeof msg.content === "string" ? msg.content : "";
      // Clarification-only text → force fast_query with original query; never submit.
      if (looksLikeClarificationText(content) || !hasSuccessfulDataTool(state)) {
        if (state.lastDataError && /ASSETS_REQUIRED|assets 不能为空|所有资产均无法识别|无法识别资产|MISSING_ASSET/i.test(state.lastDataError.message + state.lastDataError.code)) {
          break; // real upstream missing-assets — stop, do not ask user
        }
        const fields = fieldsFromUserQuery(query);
        const forced = await executeSkillTool(apiKey, "fast_query", {
          assets: extractAssetsFromQuery(query),
          query_type: inferFastQueryType(query, fields),
          fields,
          user_query: query,
          task_id: state.taskId,
        }, state, query, deadline);
        if (!forced.ok && state.lastDataError && /ASSETS_REQUIRED|assets 不能为空|所有资产均无法识别|无法识别资产|MISSING_ASSET/i.test(state.lastDataError.message + state.lastDataError.code)) {
          break;
        }
        messages.push({
          role: "user",
          content: "系统强制：禁止向用户索要代码/名称。已代为调用 fast_query（user_query=原话）。结果：" + forced.content.slice(0, 4000) + "。若仍无标的，用上游错误写 finish_report，勿再澄清。",
        });
        continue;
      }
      if (content.trim()) {
        try {
          const cleaned = content.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
          const parsed = JSON.parse(cleaned) as Record<string, unknown>;
          if (parsed.title || parsed.summary_md) {
            const title = String(parsed.title || "智能分析");
            const summary = String(parsed.summary_md || parsed.summary || "");
            if (looksLikeClarificationText(title + summary)) {
              const fields = fieldsFromUserQuery(query);
              await executeSkillTool(apiKey, "fast_query", {
                assets: extractAssetsFromQuery(query),
                query_type: inferFastQueryType(query, fields),
                fields,
                user_query: query,
                task_id: state.taskId,
              }, state, query, deadline);
              continue;
            }
            state.finish = {
              title,
              summary_md: summary,
              sections: Array.isArray(parsed.sections)
                ? (parsed.sections as Array<Record<string, unknown>>).map((s) => ({
                    heading: String(s.heading || "要点"),
                    body_md: String(s.body_md || ""),
                  }))
                : [],
            };
          }
        } catch {
          if (!looksLikeClarificationText(content)) {
            state.finish = {
              title: "智能分析",
              summary_md: content.slice(0, 1200),
              sections: [],
            };
          } else {
            const fields = fieldsFromUserQuery(query);
            await executeSkillTool(apiKey, "fast_query", {
              assets: extractAssetsFromQuery(query),
              query_type: inferFastQueryType(query, fields),
              fields,
              user_query: query,
              task_id: state.taskId,
            }, state, query, deadline);
            continue;
          }
        }
      }
      break;
    }

    let finished = false;
    for (const tc of toolCalls) {
      if (Date.now() >= deadline) break;
      const tcObj = (tc && typeof tc === "object") ? tc as Record<string, unknown> : {};
      const fn = (tcObj.function && typeof tcObj.function === "object")
        ? tcObj.function as Record<string, unknown>
        : {};
      const tName = String(fn.name || "");
      let args: Record<string, unknown> = {};
      try {
        args = JSON.parse(String(fn.arguments || "{}")) as Record<string, unknown>;
      } catch {
        args = {};
      }
      const result = await executeSkillTool(apiKey, tName, args, state, query, deadline);
      messages.push({
        role: "tool",
        tool_call_id: String(tcObj.id || ""),
        content: result.content,
      });
      if (tName === "finish_report") {
        if (result.ok) {
          finished = true;
          break;
        }
        // Rejected finish → force fast_query once if no data tool yet
        if (!hasSuccessfulDataTool(state)) {
          const fields = fieldsFromUserQuery(query);
          const forced = await executeSkillTool(apiKey, "fast_query", {
            assets: extractAssetsFromQuery(query),
            query_type: inferFastQueryType(query, fields),
            fields,
            user_query: query,
            task_id: state.taskId,
          }, state, query, deadline);
          messages.push({
            role: "user",
            content: "finish_report 被拒绝。已强制 fast_query：" + forced.content.slice(0, 4000) + "。请基于工具结果 finish_report，禁止请用户补充代码。",
          });
        }
      }
    }
    if (finished) break;
    // Cheap anti-hang: metric-only report already yielded a table — do not keep looping into confirm/index invent.
    if (
      state.lastReportNorm &&
      state.lastReportNorm.metrics.some((m) => m.valueDisplay !== "—") &&
      !/回测|筛选|全A|放量|创新高/.test(query)
    ) {
      break;
    }
    if (state.lastDataError && /所有资产均无法识别|ASSETS_REQUIRED|assets 不能为空|无法识别资产/i.test(state.lastDataError.message)) {
      break;
    }
  }

  const latency_ms = Math.max(0, Date.now() - started);
  // Drop clarification-only finish
  if (state.finish && (looksLikeClarificationText(state.finish.title + state.finish.summary_md) || !hasSuccessfulDataTool(state))) {
    state.finish = undefined;
  }
  const hasArtifacts =
    state.tables.length > 0 ||
    state.charts.length > 0 ||
    state.series.length > 0 ||
    !!state.kpis ||
    hasSuccessfulDataTool(state) ||
    (!!state.finish && hasSuccessfulDataTool(state));

  if (!hasArtifacts) {
    const lastErr = [...state.toolTrace].reverse().find((t) => !t.ok);
    const upstreamMsg = state.lastDataError?.message || lastErr?.detail || "Agent 环未产出可用结果。";
    const upstreamCode = state.lastDataError?.code || (
      /quota|额度/i.test(upstreamMsg) ? "quota" :
      /timeout|超时/i.test(upstreamMsg) ? "timeout" :
      /ASSETS_REQUIRED|assets 不能为空|MISSING_ASSET/i.test(upstreamMsg) ? "UPSTREAM_ERROR" :
      "UPSTREAM_ERROR"
    );
    const http = upstreamCode === "quota" ? 429 : (/timeout/i.test(upstreamCode) || /超时/.test(upstreamMsg) ? 504 : 502);
    return json({
      ok: false,
      error: {
        code: upstreamCode === "ASSETS_REQUIRED" ? "UPSTREAM_ERROR" : upstreamCode,
        message: upstreamMsg,
        retryable: !/ASSETS_REQUIRED|assets 不能为空|所有资产均无法识别|无法识别资产|MISSING_ASSET/i.test(upstreamMsg),
        tool: state.lastDataError?.tool || lastErr?.tool,
        upstream: { provider: "quantbuddy", code: state.lastDataError?.code || lastErr?.detail },
      },
      report: {
        title: "分析未完成",
        summary_md: `上游未返回可用数据：${upstreamMsg}`,
        sections: [],
        tables: [],
        tool_trace: state.toolTrace,
        sources: state.sources,
        disclaimer: NL_ANALYZE_DISCLAIMER,
        latency_ms,
      },
      meta: { mode: "skill_direct", model: modelUsed, steps, ru_used: state.ruUsed || null, as_of: state.asOf },
    } satisfies NlAnalyzeResponse, http, NL_ANALYZE_HEADERS);
  }

  const report = synthesizeReportFromState(query, state, latency_ms);
  return json({
    ok: true,
    report,
    meta: {
      mode: "skill_direct",
      model: modelUsed,
      steps,
      ru_used: state.ruUsed || null,
      as_of: state.asOf,
      task_id: state.taskId,
    },
  } satisfies NlAnalyzeResponse, 200, NL_ANALYZE_HEADERS);
}


function resolveDshBridgeUrl(env: Env): string {
  const raw = (env.DSH_BRIDGE_URL || "http://127.0.0.1:8789").trim().replace(/\/$/, "");
  return raw || "http://127.0.0.1:8789";
}

function parseMarkdownTables(md: string): NlAnalyzeTable[] {
  const lines = md.split(/\r?\n/);
  const tables: NlAnalyzeTable[] = [];
  let i = 0;
  while (i < lines.length - 1) {
    const header = lines[i];
    const sep = lines[i + 1];
    if (
      /^\s*\|/.test(header) &&
      /^\s*\|?\s*:?-{3,}/.test(sep)
    ) {
      const splitRow = (row: string) =>
        row
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((c) => c.trim());
      const columns = splitRow(header);
      i += 2;
      const rows: Array<Array<string | number | null>> = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        const cells = splitRow(lines[i]);
        rows.push(cells.map((c) => {
          const n = Number(c.replace(/,/g, ""));
          return c !== "" && Number.isFinite(n) && /^-?\d/.test(c.replace(/,/g, "")) ? n : c;
        }));
        i += 1;
      }
      if (columns.length && rows.length) {
        tables.push({ title: `表 ${tables.length + 1}`, columns, rows });
      }
      continue;
    }
    i += 1;
  }
  return tables;
}

/** Strip English CoT / thinking dumps from DSH assistant text. */
function stripDshReasoning(raw: string): string {
  let text = String(raw || "");
  // XML-ish think blocks
  text = text.replace(/<think>[\s\S]*?<\/think>/gi, "");
  text = text.replace(/<thinking>[\s\S]*?<\/thinking>/gi, "");
  text = text.replace(/<reasoning>[\s\S]*?<\/reasoning>/gi, "");
  // Fenced thinking / analysis blocks
  text = text.replace(/```(?:thinking|reasoning|analysis|thought)[\s\S]*?```/gi, "");
  // Common English chain-of-thought headers / mono dumps
  text = text.replace(/^(?:Thinking|Reasoning|Analysis|Thought process|Chain of thought|Internal monologue)\s*[:：].*$/gim, "");
  // Drop long English-only paragraphs that look like step narration
  const paras = text.split(/\n{2,}/);
  const kept: string[] = [];
  for (const p of paras) {
    const s = p.trim();
    if (!s) continue;
    const hasCJK = /[\u4e00-\u9fff]/.test(s);
    const looksTable = /^\s*\|/.test(s) || /\|\s*-{3,}/.test(s);
    const looksHeading = /^#{1,6}\s+/.test(s);
    const looksList = /^\s*([-*•]|\d+[.)])\s+/.test(s);
    const engRatio = (s.match(/[A-Za-z]/g) || []).length / Math.max(s.length, 1);
    const looksCoT =
      /\b(I need to|Let me|I'll|I will|First,|Next,|Then,|So I|The user asked|Looking at|Based on my|step by step)\b/i.test(s) ||
      (/\b(function|const|await|return|import)\b/.test(s) && !hasCJK);
    if (!hasCJK && !looksTable && !looksHeading && !looksList && (looksCoT || (engRatio > 0.55 && s.length > 80))) {
      continue;
    }
    kept.push(s);
  }
  return kept.join("\n\n").trim();
}

function pickChineseSummary(cleaned: string, query: string, tables: NlAnalyzeTable[]): string {
  const fallbackEmpty =
    tables.length === 0
      ? `已完成对「${query.slice(0, 40)}」的分析；本次未解析出可用表格/图表，请查看下方要点或换个问法重试。`
      : `已完成对「${query.slice(0, 40)}」的分析，详见下方表格。`;
  if (!cleaned) return fallbackEmpty;

  // Prefer last markdown heading block's following paragraph
  const headingRe = /^#{1,3}\s+(.+)$/gm;
  let lastHeadingIdx = -1;
  let m: RegExpExecArray | null;
  while ((m = headingRe.exec(cleaned))) lastHeadingIdx = m.index;
  const fromHeading = lastHeadingIdx >= 0 ? cleaned.slice(lastHeadingIdx) : cleaned;

  const chunks = fromHeading
    .split(/\n{2,}/)
    .map((c) => c.trim())
    .filter(Boolean)
    .filter((c) => !/^\s*\|/.test(c) && !/\|\s*-{3,}/.test(c));

  // Prefer last Chinese-rich paragraph
  const chinese = chunks.filter((c) => /[\u4e00-\u9fff]/.test(c) && !/^#{1,6}\s/.test(c));
  let summary = (chinese.length ? chinese[chinese.length - 1] : chunks[chunks.length - 1] || cleaned).trim();
  // Drop heading markers in summary
  summary = summary.replace(/^#{1,6}\s+/, "").replace(/\n+/g, " ").trim();
  if (summary.length > 560) summary = summary.slice(0, 557) + "…";
  return summary || fallbackEmpty;
}

function reportFromDshText(query: string, text: string, latency_ms: number): NlAnalyzeReport {
  const cleaned = stripDshReasoning(text);
  const titleMatch = cleaned.match(/^#{1,3}\s+(.+)$/m) || text.match(/^#{1,3}\s+(.+)$/m);
  const title = ((titleMatch && titleMatch[1]) || "").trim() || `问询：${query.slice(0, 48)}`;
  const tables = parseMarkdownTables(cleaned || text);
  const summary_md = pickChineseSummary(cleaned, query, tables);
  const body = cleaned || "（上游未返回可展示的中文结论。）";
  const sections: NlAnalyzeSection[] = [];
  if (body && body !== summary_md) {
    // Cap section body to avoid dumping huge CoT if strip missed some
    const bodyCap = body.length > 6000 ? body.slice(0, 6000) + "\n\n…（已截断）" : body;
    sections.push({ heading: "分析", body_md: bodyCap });
  } else if (!tables.length) {
    sections.push({ heading: "分析", body_md: summary_md });
  }
  return {
    title,
    summary_md,
    sections,
    tables,
    disclaimer: NL_ANALYZE_DISCLAIMER,
    latency_ms,
    risk_lines: [...NL_ANALYZE_RISK_LINES],
  };
}

type DshAskResult = {
  ok?: boolean;
  text?: string;
  error?: string;
  skills?: string[];
  latency_ms?: number;
  model?: unknown;
  session_id?: string;
};
type DshJobCreateResponse = {
  ok?: boolean;
  job_id?: string;
  status?: string;
  error?: string;
  timeout_s?: number;
};
type DshJobStatusResponse = {
  ok?: boolean;
  job_id?: string;
  status?: string;
  query?: string;
  error?: string;
  result?: DshAskResult | null;
  created_at?: number;
  started_at?: number | null;
  finished_at?: number | null;
  timeout_s?: number;
};

function mapDshResultToResponse(
  query: string,
  upstream: DshAskResult,
  started: number,
  bridge: string,
  extraMeta: Record<string, unknown> = {},
): Response {
  const latency = () => Math.max(0, Date.now() - started);
  if (!upstream?.ok || !(upstream.text || "").trim()) {
    const msg = (upstream && (upstream.error || (!upstream.ok ? "DSH Agent 无有效输出" : ""))) || "DSH bridge 无有效输出";
    return json({
      ok: false,
      error: { code: "UPSTREAM_ERROR", message: String(msg).slice(0, 500), retryable: true },
      report: {
        title: "分析暂不可用",
        summary_md: `_${String(msg).slice(0, 300)}_`,
        sections: [],
        tables: [],
        disclaimer: NL_ANALYZE_DISCLAIMER,
        latency_ms: latency(),
      },
      meta: {
        mode: "dsh",
        bridge,
        skills: upstream?.skills,
        model: upstream?.model,
        dsh_latency_ms: upstream?.latency_ms,
        worker_build: WORKER_BUILD,
        ...extraMeta,
      },
    } satisfies NlAnalyzeResponse, 504, NL_ANALYZE_HEADERS);
  }
  const text = String(upstream.text).trim();
  return json({
    ok: true,
    report: reportFromDshText(query, text, latency()),
    meta: {
      mode: "dsh",
      bridge,
      skills: upstream.skills,
      model: upstream.model,
      dsh_latency_ms: upstream.latency_ms,
      worker_build: WORKER_BUILD,
      ...extraMeta,
    },
  } satisfies NlAnalyzeResponse, 200, NL_ANALYZE_HEADERS);
}

/** Create async DSH bridge job; returns immediately with job_id (phone-safe). */
async function startDshAnalyzeJob(env: Env, query: string, started: number): Promise<Response> {
  const bridge = resolveDshBridgeUrl(env);
  try {
    const res = await fetch(`${bridge}/v1/jobs`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ query, timeout_s: 360 }),
    });
    const rawText = await res.text();
    let body: DshJobCreateResponse | null = null;
    try {
      body = JSON.parse(rawText) as DshJobCreateResponse;
    } catch {
      return json({
        ok: false,
        error: { code: "UPSTREAM_ERROR", message: `DSH bridge /v1/jobs 返回非 JSON（HTTP ${res.status}）。`, retryable: true },
        meta: { mode: "dsh", bridge, http_status: res.status, worker_build: WORKER_BUILD },
      } satisfies NlAnalyzeResponse, 502, NL_ANALYZE_HEADERS);
    }
    const jobId = body?.job_id;
    if (!res.ok || !body?.ok || !jobId) {
      const msg = body?.error || `DSH bridge /v1/jobs HTTP ${res.status}`;
      return json({
        ok: false,
        error: { code: "UPSTREAM_ERROR", message: String(msg).slice(0, 500), retryable: true },
        meta: { mode: "dsh", bridge, http_status: res.status, worker_build: WORKER_BUILD },
      } satisfies NlAnalyzeResponse, res.status >= 400 ? res.status : 502, NL_ANALYZE_HEADERS);
    }
    return json({
      ok: true,
      async: true,
      job_id: jobId,
      poll_path: `/api/nl-analyze/jobs/${jobId}`,
      meta: {
        mode: "dsh",
        bridge,
        worker_build: WORKER_BUILD,
        timeout_s: body.timeout_s ?? 360,
        enqueue_ms: Math.max(0, Date.now() - started),
      },
    }, 202, NL_ANALYZE_HEADERS);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return json({
      ok: false,
      error: { code: "UPSTREAM_ERROR", message: `无法连接 DSH bridge（${bridge}）：${msg.slice(0, 200)}`, retryable: true },
      report: {
        title: "分析暂不可用",
        summary_md: `_DSH bridge 不可达。_`,
        sections: [],
        tables: [],
        disclaimer: NL_ANALYZE_DISCLAIMER,
        latency_ms: Math.max(0, Date.now() - started),
      },
      meta: { mode: "dsh", bridge, worker_build: WORKER_BUILD },
    } satisfies NlAnalyzeResponse, 503, NL_ANALYZE_HEADERS);
  }
}

async function handleNlAnalyzeJob(env: Env, jobId: string): Promise<Response> {
  const bridge = resolveDshBridgeUrl(env);
  const started = Date.now();
  try {
    const res = await fetch(`${bridge}/v1/jobs/${encodeURIComponent(jobId)}`, {
      method: "GET",
      headers: { accept: "application/json" },
    });
    const rawText = await res.text();
    let body: DshJobStatusResponse | null = null;
    try {
      body = JSON.parse(rawText) as DshJobStatusResponse;
    } catch {
      return json({
        ok: false,
        error: { code: "UPSTREAM_ERROR", message: `DSH bridge job 返回非 JSON（HTTP ${res.status}）。`, retryable: true },
        meta: { mode: "dsh", bridge, job_id: jobId, http_status: res.status, worker_build: WORKER_BUILD },
      } satisfies NlAnalyzeResponse, 502, NL_ANALYZE_HEADERS);
    }
    if (res.status === 404) {
      return json({
        ok: false,
        error: { code: "not_found", message: "任务不存在或已过期。", retryable: false },
        meta: { mode: "dsh", bridge, job_id: jobId, worker_build: WORKER_BUILD },
      } satisfies NlAnalyzeResponse, 404, NL_ANALYZE_HEADERS);
    }
    if (!res.ok || !body?.ok) {
      return json({
        ok: false,
        error: { code: "UPSTREAM_ERROR", message: String(body?.error || `DSH job HTTP ${res.status}`).slice(0, 500), retryable: true },
        meta: { mode: "dsh", bridge, job_id: jobId, worker_build: WORKER_BUILD },
      } satisfies NlAnalyzeResponse, res.status >= 400 ? res.status : 502, NL_ANALYZE_HEADERS);
    }
    const status = String(body.status || "queued");
    if (status === "queued" || status === "running") {
      return json({
        ok: true,
        async: true,
        job_id: jobId,
        status,
        meta: {
          mode: "dsh",
          bridge,
          job_id: jobId,
          worker_build: WORKER_BUILD,
          created_at: body.created_at,
          started_at: body.started_at,
        },
      }, 200, NL_ANALYZE_HEADERS);
    }
    if (status === "error" && !body.result) {
      const msg = body.error || "DSH job failed";
      return json({
        ok: false,
        error: { code: "UPSTREAM_ERROR", message: String(msg).slice(0, 500), retryable: true },
        report: {
          title: "分析暂不可用",
          summary_md: `_${String(msg).slice(0, 300)}_`,
          sections: [],
          tables: [],
          disclaimer: NL_ANALYZE_DISCLAIMER,
          latency_ms: Math.max(0, Date.now() - started),
        },
        meta: { mode: "dsh", bridge, job_id: jobId, worker_build: WORKER_BUILD, status },
      } satisfies NlAnalyzeResponse, 504, NL_ANALYZE_HEADERS);
    }
    const upstream = (body.result || { ok: false, error: body.error || "empty result" }) as DshAskResult;
    // Prefer wall clock from job timestamps when available
    const jobStartedMs = body.created_at ? Math.floor(Number(body.created_at) * 1000) : started;
    const query = (body.query || "").trim() || `任务 ${jobId.slice(0, 8)}`;
    return mapDshResultToResponse(query, upstream, jobStartedMs, bridge, {
      job_id: jobId,
      status,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return json({
      ok: false,
      error: { code: "UPSTREAM_ERROR", message: `无法连接 DSH bridge（${bridge}）：${msg.slice(0, 200)}`, retryable: true },
      meta: { mode: "dsh", bridge, job_id: jobId, worker_build: WORKER_BUILD },
    } satisfies NlAnalyzeResponse, 503, NL_ANALYZE_HEADERS);
  }
}


async function handleNlAnalyze(request: Request, env: Env): Promise<Response> {
  const started = Date.now();
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: { code: "bad_request", message: "请求体必须是 JSON。" } } satisfies NlAnalyzeResponse, 400, NL_ANALYZE_HEADERS);
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return json({ ok: false, error: { code: "bad_request", message: "请求体必须是对象：{ query, assets?, locale? }。" } } satisfies NlAnalyzeResponse, 400, NL_ANALYZE_HEADERS);
  }
  const raw = body as Record<string, unknown>;
  const query = typeof raw.query === "string" ? raw.query.trim() : "";
  if (!query) {
    return json({ ok: false, error: { code: "bad_request", message: "query 不能为空。" } } satisfies NlAnalyzeResponse, 400, NL_ANALYZE_HEADERS);
  }
  let assetsIn: string[] | undefined;
  if (raw.assets !== undefined) {
    if (!Array.isArray(raw.assets) || raw.assets.some((item) => typeof item !== "string")) {
      return json({ ok: false, error: { code: "bad_request", message: "assets 必须是字符串数组（可选）。" } } satisfies NlAnalyzeResponse, 400, NL_ANALYZE_HEADERS);
    }
    assetsIn = raw.assets as string[];
  }
  if (raw.locale !== undefined && typeof raw.locale !== "string") {
    return json({ ok: false, error: { code: "bad_request", message: "locale 必须是字符串（可选）。" } } satisfies NlAnalyzeResponse, 400, NL_ANALYZE_HEADERS);
  }

  const mode = String(env.NL_ANALYZE_MODE || "dsh").trim().toLowerCase();
  // Default product path: DSH Agent + filesystem skills. No silent skill_direct fallback.
  if (mode !== "skill_direct") {
    return startDshAnalyzeJob(env, query, started);
  }

  // Legacy escape hatch only when NL_ANALYZE_MODE=skill_direct is set explicitly.
  const apiKey = resolveQbsApiKey(env);
  if (!apiKey) {
    const latency_ms = Math.max(0, Date.now() - started);
    return json({
      ok: false,
      error: { code: "UPSTREAM_ERROR", message: "服务端未配置 QBS_API_KEY / QUANT_BUDDY_API_KEY，无法调用行情上游。" },
      report: {
        title: "分析暂不可用",
        summary_md: "_未配置 Quant Buddy API Key。_",
        sections: [],
        tables: [],
        sources: [],
        disclaimer: NL_ANALYZE_DISCLAIMER,
        latency_ms,
      },
      meta: { mode: "skill_direct" },
    } satisfies NlAnalyzeResponse, 503, NL_ANALYZE_HEADERS);
  }

  try {
    const heuristic = await tryHeuristicFastQuote(apiKey, query, assetsIn, started);
    if (heuristic) return json(heuristic, 200, NL_ANALYZE_HEADERS);
  } catch {
    // fall through to full agent
  }

  return runSkillDirectAgent(env, apiKey, query, started);
}


/** Writer-frozen Chinese copy for /ask (skill_direct / artifacts). */
const ASK_COPY = {
  doc_title: "巴小卡股市监控 · 问询",
  page_title: "自然语言问询",
  page_blurb: "用一句话提问：行情、财报、筛选或回测。由技能直调出表、序列与图；不构成买卖建议。",
  nav_ask: "问询",
  input_placeholder: "例如：查一下贵州茅台最新收盘价、涨跌幅和成交额。",
  example_chip: "查一下贵州茅台最新收盘价、涨跌幅和成交额。",
  example_chip_report: "列出宁德时代最近报告期 ROE、净利润和资产负债率",
  example_chip_report_short: "宁德 · ROE/净利/负债率",
  example_chip_screen: "筛选今天 14:30 全 A 股中，近 60 个交易日创新高、成交额高于过去 20 日均值 2 倍、且涨幅排名靠前的公司。",
  example_chip_screen_short: "全A · 60日新高 · 放量×2 · Top10",
  example_chip_backtest: "回测低 PE + 高 ROE 组合，相对沪深 300 画净值",
  example_chip_backtest_short: "低PE+高ROE · 回测净值",
  btn_submit: "生成报告",
  btn_retry: "重试",
  loading: "正在生成报告；回测可 3–5 分钟，请保持页面在前台，勿切后台/锁屏。",
  loading_wait: "正在生成报告；回测可 3–5 分钟，请保持页面在前台，勿切后台/锁屏。",
  loading_title: "正在分析…",
  tip_skill: "进度：调用技能",
  tip_data: "进度：取数",
  tip_conclude: "进度：生成结论",
  empty: "输入问题后点「生成报告」。",
  error_generic: "报告生成失败，请稍后重试。",
  error_timeout: "请求超时，请缩小问题或稍后重试。",
  error_network: "连接中断（可能切后台或网络抖动）。服务端可能仍在分析，请稍后重试；尽量保持页面在前台。",
  error_aborted: "请求已取消。若非主动取消，请保持页面在前台后重试。",
  error_no_match: "上游未返回可用数据，请换个写法或稍后重试。",
  error_quota: "上游额度不足，请稍后再试。",
  error_unsupported: "分析未完成，请稍后重试或换个问法。",
  section_summary: "一句话结论",
  section_points: "要点",
  section_table: "数据明细",
  section_sources: "来源",
  section_risk: "风险提示",
  section_charts: "图表",
  section_series: "序列",
  kpi_close: "收盘价",
  kpi_change: "涨跌幅",
  kpi_amount: "成交额",
  label_trade_day: "交易日",
  label_delay: "数据延迟",
  price_basis: "价格按不复权行情",
  badge: "智能分析",
  disclaimer: NL_ANALYZE_DISCLAIMER,
  risk_lines: [
    "本报告由规则与模型自动生成，仅供观察，不构成投资建议。",
    "行情可能有延迟；请以交易所或券商终端为准。",
    "过往表现不代表未来收益。",
  ],
  points_bullets: [
    "结果由 Quant Buddy 技能直调生成。",
    "有表出表、有序列画折线、有图直接展示。",
    "以下仅供观察，未做投资决策建议。",
  ],
} as const;

function renderAskPage(url: URL): Response {
  const content = askPageView();
  return html(pageShell(content, ASK_COPY.doc_title, ASK_COPY.page_blurb));
}

function askPageView(): string {
  const copyJson = JSON.stringify(ASK_COPY).replace(/</g, "\\u003c");
  return `<style>
    .ask-page{--ask-up:#ff4d4f;--ask-dn:#3dd68c;--ask-err:#ff8a8a;padding-top:38px;width:min(880px,calc(100% - 40px))}
    .ask-page .site-nav{margin-bottom:28px}
    .ask-hero{padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:18px}
    .ask-hero h1{margin:0 0 8px;font-size:clamp(28px,5vw,40px);letter-spacing:-.03em}
    .ask-lede{margin:0;color:var(--muted);font-size:13px;line-height:1.55;max-width:640px}
    .ask-card{border:1px solid var(--line);border-radius:14px;background:linear-gradient(145deg,rgba(19,24,29,.96),rgba(13,16,20,.96));padding:16px;margin-bottom:14px}
    .ask-card h2{margin:0 0 12px;font-size:14px;font-weight:650;color:#c9d0d6;display:flex;justify-content:space-between;align-items:center;gap:8px}
    .ask-card h2 .sub{color:var(--muted);font-weight:500;font-size:11px}
    .ask-form{display:grid;gap:10px}
    .ask-form textarea{width:100%;min-height:88px;resize:vertical;padding:12px 14px;border-radius:10px;border:1px solid #2a3338;background:#0b0e11;color:var(--text);font:400 14px/1.5 "PingFang SC",Inter,ui-sans-serif,sans-serif}
    .ask-form textarea:focus{outline:none;border-color:#3d5a4a;box-shadow:0 0 0 2px rgba(111,227,162,.12)}
    .ask-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}
    .ask-hints{display:flex;flex-wrap:wrap;gap:6px}
    .ask-hint{min-height:36px;padding:8px 12px;border-radius:999px;border:1px solid var(--line);background:#0c0f12;color:#aeb7bf;font-size:12px;cursor:pointer;display:inline-flex;align-items:center}
    .ask-hint:hover,.ask-hint:focus-visible{border-color:#3d5a4a;color:var(--accent);outline:none}
    .ask-go{min-height:44px;height:44px;padding:0 16px;border-radius:9px;border:0;background:linear-gradient(135deg,#2a5a42,#1e3d2e);color:var(--accent);font:650 13px "PingFang SC",sans-serif;cursor:pointer}
    .ask-go:hover:not(:disabled){filter:brightness(1.08)}
    .ask-go:disabled{opacity:.45;cursor:not-allowed}
    .ask-meta{color:#59616a;font-size:11px}
    .ask-state{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;border-radius:10px;border:1px solid #2a3338;background:#0c1014;margin-bottom:12px}
    .ask-state.loading{border-color:#2a4034}
    .ask-state.err{border-color:#4a3030;background:rgba(255,77,79,.05)}
    .ask-state.empty{border-style:dashed}
    .ask-spin{width:16px;height:16px;border-radius:50%;border:2px solid #315641;border-top-color:var(--accent);animation:ask-r .8s linear infinite;flex-shrink:0;margin-top:2px}
    @keyframes ask-r{to{transform:rotate(360deg)}}
    .ask-state p{margin:0;font-size:13px;line-height:1.5;color:#aeb7bf;flex:1}
    .ask-loading-copy{flex:1;display:grid;gap:4px;min-width:0}
    .ask-loading-copy p{flex:none}
    .ask-loading-copy #ask-loading-wait{color:#aeb7bf}
    .ask-loading-copy #ask-loading-tip{color:#87919b;font-size:12px}
    .ask-loading-copy #ask-loading-elapsed{color:#87919b;font-weight:500;font-variant-numeric:tabular-nums}
    .ask-state.err p{color:#e8c4c4}
    .ask-state b{color:#e8eef2}
    .ask-retry{min-height:44px;height:44px;padding:0 14px;border-radius:8px;border:1px solid #4a3030;background:transparent;color:#e8c4c4;font:650 12px "PingFang SC",sans-serif;cursor:pointer;flex-shrink:0}
    .ask-retry:hover{border-color:var(--ask-err);color:#fff}
    .ask-report-head{display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:12px}
    .ask-report-head h3{margin:0;font-size:18px;letter-spacing:-.02em}
    .ask-badge{display:inline-flex;align-items:center;height:22px;padding:0 9px;border-radius:999px;background:rgba(111,227,162,.1);color:var(--accent);font:650 11px/1 sans-serif}
    .ask-summary{margin:0 0 14px;color:#c9d0d6;font-size:14px;line-height:1.6}
    .ask-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px}
    @media(max-width:899px){.ask-page{width:min(100% - 40px,880px)}.ask-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:599px){.ask-kpis{grid-template-columns:1fr}.ask-page{width:min(100% - 28px,880px);padding-top:24px}.ask-page .site-nav{margin-bottom:22px;max-width:100%;width:100%;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}.ask-page .site-nav::-webkit-scrollbar{display:none}.ask-hint{min-height:44px;padding:10px 12px;display:inline-flex;align-items:center}.ask-go{min-height:44px;height:44px}.ask-retry{min-height:44px;height:44px}.ask-row{align-items:stretch}.ask-hints{width:100%}.ask-table-wrap{max-width:100%}.ask-chips{gap:6px}}
    .ask-kpi{padding:12px;border-radius:10px;border:1px solid #1a2228;background:#0b0e11}
    .ask-kpi .lab{color:var(--muted);font-size:11px;font-weight:650;letter-spacing:.04em}
    .ask-kpi .val{margin-top:6px;font:720 22px/1.1 ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
    .ask-kpi .val.up{color:var(--ask-up)}.ask-kpi .val.dn{color:var(--ask-dn)}
    .ask-kpi .unit{color:#59616a;font-size:11px;margin-top:4px}
    .ask-table{width:100%;border-collapse:collapse;font-size:13px}
    .ask-table th,.ask-table td{padding:10px 8px;border-top:1px solid var(--line);text-align:left}
    .ask-table th{color:var(--muted);font-weight:650;font-size:11px;letter-spacing:.04em}
    .ask-table td.mono{font:650 13px ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
    .ask-table .up{color:var(--ask-up)}.ask-table .dn{color:var(--ask-dn)}
    .ask-section{margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}
    .ask-section h4{margin:0 0 8px;font-size:13px;color:#c9d0d6}
    .ask-section p,.ask-section li{margin:0;color:#aeb7bf;font-size:13px;line-height:1.55}
    .ask-section ul{margin:0;padding-left:18px}
    .ask-section li+li{margin-top:4px}
    .ask-disc{margin-top:12px;padding:10px 12px;border-radius:8px;border:1px dashed #2a3338;color:#59616a;font-size:11px;line-height:1.5}
    .ask-result[hidden],.ask-state[hidden]{display:none!important}
    .ask-chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px}
    .ask-chip{padding:4px 8px;border-radius:6px;border:1px solid #2a3338;background:#0b0e11;color:#aeb7bf;font-size:11px}
    .ask-table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #1a2228;border-radius:10px;margin-top:4px}
    .ask-table-wrap .ask-table{min-width:420px;background:#0b0e11}
    .ask-table-wrap .ask-table th{background:#0e1216;border-top:0}
    .ask-table td.rank{font:720 13px ui-monospace,Menlo,monospace;color:#aeb7bf;width:40px}
    .ask-table td.name{font-weight:650}
    .ask-empty-hit{padding:28px 12px;text-align:center;color:#59616a;font-size:13px;background:#0b0e11;border-radius:10px;border:1px solid #1a2228}
    .ask-chart{margin-top:8px;border:1px solid #1a2228;border-radius:10px;overflow:hidden;background:#0b0e11}
    .ask-chart img{display:block;width:100%;height:auto}
    .ask-series-svg{width:100%;height:180px;background:#0b0e11;border:1px solid #1a2228;border-radius:10px}
    .ask-hint.on{border-color:#315641;color:var(--accent);background:rgba(111,227,162,.06)}
    .ask-md{color:#aeb7bf;font-size:13px;line-height:1.6;word-break:break-word;overflow-wrap:anywhere}
    .ask-md>*:first-child{margin-top:0}.ask-md>*:last-child{margin-bottom:0}
    .ask-md h1,.ask-md h2,.ask-md h3,.ask-md h4,.ask-md h5,.ask-md h6{margin:12px 0 8px;color:#c9d0d6;font-weight:650;line-height:1.35;letter-spacing:-.01em}
    .ask-md h1{font-size:18px}.ask-md h2{font-size:16px}.ask-md h3{font-size:15px}.ask-md h4{font-size:14px}.ask-md h5,.ask-md h6{font-size:13px}
    .ask-md p{margin:0 0 10px;color:#aeb7bf;font-size:13px;line-height:1.55}
    .ask-summary .ask-md p{color:#c9d0d6;font-size:14px;line-height:1.6}
    .ask-md ul,.ask-md ol{margin:0 0 10px;padding-left:1.35em}
    .ask-md li{margin:0 0 4px;color:#aeb7bf;font-size:13px;line-height:1.55}
    .ask-md li>ul,.ask-md li>ol{margin:4px 0 0}
    .ask-md strong,.ask-md b{color:#e8eef2;font-weight:650}
    .ask-md em,.ask-md i{font-style:italic}
    .ask-md a{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
    .ask-md a:hover{filter:brightness(1.08)}
    .ask-md blockquote{margin:0 0 10px;padding:8px 12px;border-left:3px solid #315641;background:rgba(111,227,162,.05);color:#aeb7bf;border-radius:0 8px 8px 0}
    .ask-md hr{border:0;border-top:1px solid #2a3338;margin:12px 0}
    .ask-md code{font:650 12px/1.4 ui-monospace,Menlo,monospace;padding:1px 5px;border-radius:4px;background:#0b0e11;border:1px solid #1a2228;color:#c9d0d6}
    .ask-md pre{margin:0 0 10px;padding:12px;border-radius:10px;border:1px solid #1a2228;background:#0b0e11;overflow-x:auto;-webkit-overflow-scrolling:touch}
    .ask-md pre code{display:block;padding:0;border:0;background:transparent;font-weight:500;font-size:12px;line-height:1.5;color:#c9d0d6;white-space:pre}
    .ask-md .ask-table-wrap{margin:8px 0 10px}
    .ask-md table{width:100%;border-collapse:collapse;font-size:13px;min-width:420px;background:#0b0e11}
    .ask-md th,.ask-md td{padding:10px 8px;border-top:1px solid var(--line);text-align:left}
    .ask-md th{color:var(--muted);font-weight:650;font-size:11px;letter-spacing:.04em;background:#0e1216;border-top:0}
  </style>
  <main class="ask-page">
    ${siteNavigation("ask")}
    <header class="ask-hero">
      <p class="eyebrow"><span class="pulse" aria-hidden="true"></span>仅供观察 · 非买卖建议</p>
      <h1>${escapeHtml(ASK_COPY.page_title)}</h1>
      <p class="ask-lede">${escapeHtml(ASK_COPY.page_blurb)}</p>
    </header>
    <section class="ask-card">
      <h2>提问 <span class="sub">例句可点填</span></h2>
      <form class="ask-form" id="ask-form" novalidate>
        <label for="ask-query" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)">问题</label>
        <textarea id="ask-query" name="query" rows="3" placeholder="${escapeHtml(ASK_COPY.input_placeholder)}" autocomplete="off"></textarea>
        <div class="ask-row">
          <div class="ask-hints" aria-label="例句">
            <button type="button" class="ask-hint" data-chip="${escapeHtml(ASK_COPY.example_chip)}">${escapeHtml(ASK_COPY.example_chip)}</button>
            <button type="button" class="ask-hint" data-chip="600519 最新行情">600519 最新行情</button>
            <button type="button" class="ask-hint" data-chip="${escapeHtml(ASK_COPY.example_chip_report)}">${escapeHtml(ASK_COPY.example_chip_report_short)}</button>
            <button type="button" class="ask-hint" data-chip="${escapeHtml(ASK_COPY.example_chip_screen)}">${escapeHtml(ASK_COPY.example_chip_screen_short)}</button>
            <button type="button" class="ask-hint" data-chip="${escapeHtml(ASK_COPY.example_chip_backtest)}">${escapeHtml(ASK_COPY.example_chip_backtest_short)}</button>
          </div>
          <button class="ask-go" id="ask-submit" type="submit">${escapeHtml(ASK_COPY.btn_submit)}</button>
        </div>
        <div class="ask-meta">${escapeHtml(ASK_COPY.price_basis)} · 密钥仅服务端 · 回测可能需数分钟</div>
      </form>
    </section>
    <div id="ask-empty" class="ask-state empty" role="status"><p>${escapeHtml(ASK_COPY.empty)}</p></div>
    <div id="ask-loading" class="ask-state loading" hidden role="status" aria-live="polite">
      <div class="ask-spin" aria-hidden="true"></div>
      <div class="ask-loading-copy">
        <p><b id="ask-loading-title">${escapeHtml(ASK_COPY.loading_title)}</b> <span id="ask-loading-elapsed">已用时 0 秒</span></p>
        <p id="ask-loading-wait">${escapeHtml(ASK_COPY.loading_wait)}</p>
        <p id="ask-loading-tip">${escapeHtml(ASK_COPY.tip_skill)}</p>
      </div>
    </div>
    <div id="ask-error" class="ask-state err" hidden role="alert">
      <p id="ask-error-text"></p>
      <button type="button" class="ask-retry" id="ask-retry">${escapeHtml(ASK_COPY.btn_retry)}</button>
    </div>
    <section id="ask-report" class="ask-card ask-result" hidden aria-live="polite"></section>
    ${footer()}
  </main>
  <script src="https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js" crossorigin="anonymous"></script>
  <script src="https://cdn.jsdelivr.net/npm/dompurify@3.2.4/dist/purify.min.js" crossorigin="anonymous"></script>
  <script>
  (()=>{
    const COPY = ${copyJson};
    const form = document.getElementById("ask-form");
    const textarea = document.getElementById("ask-query");
    const submitBtn = document.getElementById("ask-submit");
    const emptyEl = document.getElementById("ask-empty");
    const loadingEl = document.getElementById("ask-loading");
    const errorEl = document.getElementById("ask-error");
    const errorText = document.getElementById("ask-error-text");
    const retryBtn = document.getElementById("ask-retry");
    const reportEl = document.getElementById("ask-report");
    const useMock = new URLSearchParams(location.search).get("mock") === "1";
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[ch]));
    const loadingTitleEl = document.getElementById("ask-loading-title");
    const loadingElapsedEl = document.getElementById("ask-loading-elapsed");
    const loadingWaitEl = document.getElementById("ask-loading-wait");
    const loadingTipEl = document.getElementById("ask-loading-tip");
    const progressTips = [COPY.tip_skill, COPY.tip_data, COPY.tip_conclude];
    let loadElapsedTimer = null;
    let loadTipTimer = null;
    let loadStartedAt = 0;
    let tipIndex = 0;
    function clearLoadingTimers(){
      if (loadElapsedTimer){ clearInterval(loadElapsedTimer); loadElapsedTimer = null; }
      if (loadTipTimer){ clearInterval(loadTipTimer); loadTipTimer = null; }
    }
    function startLoadingTimers(){
      clearLoadingTimers();
      loadStartedAt = Date.now();
      tipIndex = 0;
      if (loadingTitleEl) loadingTitleEl.textContent = COPY.loading_title;
      if (loadingWaitEl) loadingWaitEl.textContent = COPY.loading_wait;
      if (loadingElapsedEl) loadingElapsedEl.textContent = "已用时 0 秒";
      if (loadingTipEl) loadingTipEl.textContent = progressTips[0];
      loadElapsedTimer = setInterval(() => {
        const sec = Math.max(0, Math.floor((Date.now() - loadStartedAt) / 1000));
        if (loadingElapsedEl) loadingElapsedEl.textContent = "已用时 " + sec + " 秒";
      }, 1000);
      loadTipTimer = setInterval(() => {
        tipIndex = (tipIndex + 1) % progressTips.length;
        if (loadingTipEl) loadingTipEl.textContent = progressTips[tipIndex];
      }, 15000);
    }
    function setState(state){
      if (state !== "loading") clearLoadingTimers();
      emptyEl.hidden = state !== "empty";
      loadingEl.hidden = state !== "loading";
      errorEl.hidden = state !== "error";
      reportEl.hidden = state !== "success";
      submitBtn.disabled = state === "loading";
      if (state === "loading") startLoadingTimers();
    }
    function mapError(code){
      switch(code){
        case "timeout": case "error_timeout": return COPY.error_timeout;
        case "error_network": case "network": return COPY.error_network;
        case "error_aborted": case "aborted": case "AbortError": return COPY.error_aborted;
        case "no_match": case "error_no_match": return COPY.error_no_match;
        case "quota": case "error_quota": case "UPSTREAM_QUOTA": case "UPSTREAM_RATE_LIMIT": return COPY.error_quota;
        case "unsupported_intent": case "error_unsupported": return COPY.error_unsupported;
        case "pending_harness":
        default: return COPY.error_generic;
      }
    }
    function changeClass(pct){
      if (typeof pct !== "number" || !Number.isFinite(pct) || pct === 0) return "";
      return pct > 0 ? "up" : "dn";
    }
    function formatChange(pct){
      if (typeof pct !== "number" || !Number.isFinite(pct)) return "—";
      return (pct > 0 ? "+" : "") + pct.toFixed(2) + "%";
    }
    function mockReport(){
      const fence = String.fromCharCode(96, 96, 96);
      const summaryMd = [
        "截至 **2026-09-14**，*贵州茅台* 收盘 \`1,482.00\`，涨跌幅 **+1.28%**，成交额 48.6 亿。",
        "",
        "> 仅供观察；价格按不复权行情。",
        "",
        "可对照 [上交所](https://www.sse.com.cn) 公开披露。"
      ].join("\\n");
      const bodyMd = [
        "### 观察要点",
        "",
        "- 结果由 Quant Buddy 技能直调生成。",
        "- 有表出表、有序列画折线、有图直接展示。",
        "- 以下仅供观察，**未做**投资决策建议。",
        "",
        "1. 先看收盘与涨跌",
        "2. 再看成交额与量能",
        "",
        fence,
        "close=1482.00 chg=+1.28% amount=4.86e9",
        fence,
        "",
        "| 字段 | 值 |",
        "| --- | --- |",
        "| 代码 | \`600519\` |",
        "| 收盘 | 1482.00 |",
        "",
        "---",
        "",
        "内联代码示例：\`ROE\` / *净利润* / **资产负债率**。"
      ].join("\\n");
      return {
        title: "贵州茅台（600519）行情观察",
        summary_md: summaryMd,
        trade_day: "2026-09-14",
        latency_ms: 4200,
        kpis: { close: "1,482.00", change_pct: 1.28, amount: "48.6 亿" },
        sections: [{ heading: COPY.section_points, body_md: bodyMd }],
        tables: [{
          title: "关键行情字段（不复权）",
          columns: ["字段", "值", "说明"],
          rows: [
            ["代码", "600519.SH", "贵州茅台"],
            ["收盘价", "1482.00", "最近交易日"],
            ["涨跌幅", "+1.28%", "较前一交易日收盘"],
            ["成交额", "4.86e9", "当日累计"]
          ]
        }],
        sources: [{ name: "Quant Buddy / fast_query" }],
        disclaimer: COPY.disclaimer,
        risk_lines: COPY.risk_lines
      };
    }
    function extractKpis(report){
      if (report.kpis && typeof report.kpis === "object") return report.kpis;
      const kpis = {};
      const table = Array.isArray(report.tables) && report.tables[0];
      if (!table || !Array.isArray(table.rows)) return kpis;
      for (const row of table.rows){
        if (!Array.isArray(row) || row.length < 2) continue;
        const key = String(row[0] || "");
        const val = row[1];
        if (key.includes("收盘")) kpis.close = String(val);
        else if (key.includes("涨跌")) {
          kpis.change = String(val);
          const m = String(val).match(/([+-]?\\d+(?:\\.\\d+)?)/);
          if (m) kpis.change_pct = Number(m[1]);
        } else if (key.includes("成交额")) kpis.amount = String(val);
      }
      return kpis;
    }
    function renderSeriesSvg(series){
      if (!series || !Array.isArray(series.values) || series.values.length < 2) return "";
      const vals = series.values.map((v) => (typeof v === "number" ? v : Number(v))).filter((v) => Number.isFinite(v));
      if (vals.length < 2) {
        return '<div class="ask-section"><h4>' + esc(series.name || COPY.section_series) + '</h4><ul>' +
          series.values.slice(0, 12).map((v, i) => '<li class="mono">' + esc(String((series.dates && series.dates[i]) || i)) + ' · ' + esc(String(v)) + '</li>').join('') + '</ul></div>';
      }
      const w = 640, h = 180, pad = 16;
      const min = Math.min(...vals), max = Math.max(...vals);
      const span = Math.max(max - min, 1e-9);
      const pts = vals.map((v, i) => {
        const x = pad + (i / (vals.length - 1)) * (w - pad * 2);
        const y = pad + (1 - (v - min) / span) * (h - pad * 2);
        return x.toFixed(1) + "," + y.toFixed(1);
      }).join(" ");
      return '<div class="ask-section"><h4>' + esc(series.name || COPY.section_series) + '</h4>' +
        '<svg class="ask-series-svg" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(series.name || "series") + '">' +
        '<polyline fill="none" stroke="#6fe3a2" stroke-width="2" points="' + pts + '"/></svg></div>';
    }
    function renderMd(src){
      const text = String(src || "");
      if (!text.trim()) return "";
      try {
        if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
          const parse = (typeof marked.parse === "function") ? marked.parse.bind(marked) : marked;
          const raw = parse(text, { gfm: true, breaks: true });
          const clean = DOMPurify.sanitize(raw, {
            ALLOWED_TAGS: ["h1","h2","h3","h4","h5","h6","p","br","hr","ul","ol","li","strong","em","b","i","code","pre","a","blockquote","table","thead","tbody","tr","th","td","span","del","sup","sub"],
            ALLOWED_ATTR: ["href","title","target","rel","class","colspan","rowspan","align"],
            ALLOW_DATA_ATTR: false
          });
          const tmp = document.createElement("div");
          tmp.innerHTML = clean;
          tmp.querySelectorAll("a[href]").forEach((a) => {
            a.setAttribute("target", "_blank");
            a.setAttribute("rel", "noopener noreferrer");
            const href = a.getAttribute("href") || "";
            if (/^javascript:/i.test(href) || /^data:/i.test(href) || /^vbscript:/i.test(href)) {
              a.removeAttribute("href");
            }
          });
          tmp.querySelectorAll("table").forEach((table) => {
            if (table.parentElement && table.parentElement.classList.contains("ask-table-wrap")) return;
            const wrap = document.createElement("div");
            wrap.className = "ask-table-wrap";
            table.parentNode.insertBefore(wrap, table);
            wrap.appendChild(table);
          });
          return tmp.innerHTML;
        }
      } catch (_err) {}
      return "<p>" + esc(text).replace(/\\n/g, "<br>") + "</p>";
    }
    function renderReport(report, _intent, meta){
      const tables = Array.isArray(report.tables) ? report.tables : [];
      const charts = Array.isArray(report.charts) ? report.charts : [];
      const seriesList = Array.isArray(report.series) ? report.series : [];
      const chips = Array.isArray(report.chips) ? report.chips : [];
      const tradeDay = report.trade_day || report.tradeDay || (meta && meta.as_of) || "—";
      const latency = Number.isFinite(report.latency_ms) ? (report.latency_ms / 1000).toFixed(1) + "s" : "—";
      const summary = report.summary_md || report.summary || "";
      const sections = Array.isArray(report.sections) ? report.sections : [];
      const riskLines = Array.isArray(report.risk_lines) ? report.risk_lines : COPY.risk_lines;
      const disclaimer = report.disclaimer || COPY.disclaimer;
      const mode = (meta && meta.mode) || "skill_direct";
      const badge = COPY.badge;

      const kpis = extractKpis(report);
      const changePct = typeof kpis.change_pct === "number" ? kpis.change_pct : null;
      const changeText = kpis.change || formatChange(changePct);
      const chCls = changeClass(changePct);
      const usable = (v) => {
        if (v == null) return false;
        const s = String(v).trim();
        return s !== "" && s !== "—" && s !== "-" && s !== "null" && s !== "undefined";
      };
      const hasClose = usable(kpis.close);
      const hasChange = usable(kpis.change) || (typeof kpis.change_pct === "number" && Number.isFinite(kpis.change_pct));
      const hasAmount = usable(kpis.amount);
      const showKpis = hasClose || hasChange || hasAmount;
      const kpisHtml = showKpis
        ? ('<div class="ask-kpis" aria-label="关键指标">' +
          '<div class="ask-kpi"><div class="lab">' + esc(COPY.kpi_close) + '</div><div class="val">' + esc(hasClose ? kpis.close : "—") +
          '</div><div class="unit">元 / 股 · ' + esc(COPY.price_basis) + '</div></div>' +
          '<div class="ask-kpi"><div class="lab">' + esc(COPY.kpi_change) + '</div><div class="val ' + chCls + '">' + esc(hasChange ? changeText : "—") +
          '</div><div class="unit">较前收</div></div>' +
          '<div class="ask-kpi"><div class="lab">' + esc(COPY.kpi_amount) + '</div><div class="val">' + esc(hasAmount ? kpis.amount : "—") +
          '</div><div class="unit">元</div></div></div>')
        : "";

      const chipsHtml = chips.length
        ? '<div class="ask-chips">' + chips.map((c) => '<span class="ask-chip">' + esc(c) + '</span>').join("") + '</div>'
        : "";

      let tableHtml = "";
      for (const table of tables){
        const cols = Array.isArray(table.columns) ? table.columns : [];
        const rows = Array.isArray(table.rows) ? table.rows : [];
        // Never draw empty quote three-column 行情 table (close/chg/amount all —)
        if ((table.name === "snapshot" || /行情/.test(String(table.title || ""))) && rows.length) {
          const quoteVals = rows.filter((r) => /收盘|涨跌|成交/.test(String((r && r[0]) || ""))).map((r) => String((r && r[1]) || "").trim());
          if (quoteVals.length && quoteVals.every((v) => !v || v === "—" || v === "-" || v === "null")) continue;
        }
        tableHtml += '<div class="ask-section"><h4>' + esc(table.title || table.name || COPY.section_table) + '</h4>';
        if (!rows.length){
          tableHtml += '<div class="ask-empty-hit">暂无行</div></div>';
          continue;
        }
        tableHtml += '<div class="ask-table-wrap"><table class="ask-table"><thead><tr>' +
          cols.map((c) => '<th>' + esc(c) + '</th>').join("") + '</tr></thead><tbody>';
        for (const row of rows){
          tableHtml += '<tr>' + (Array.isArray(row) ? row : []).map((cell, i) => {
            const text = cell == null ? "—" : String(cell);
            const isChange = i > 0 && /[+-]?\\d+(\\.\\d+)?%/.test(text);
            let cls = i > 0 ? "mono" : "";
            if (i === 0 && cols[0] === "#") cls = "rank";
            if (isChange){
              if (text.trim().startsWith("+")) cls += " up";
              else if (text.trim().startsWith("-")) cls += " dn";
            }
            return '<td class="' + cls.trim() + '">' + esc(text) + '</td>';
          }).join("") + '</tr>';
        }
        tableHtml += '</tbody></table></div></div>';
      }

      let chartsHtml = "";
      for (const ch of charts){
        const b64 = ch.data_base64 || ch.base64 || "";
        const mime = ch.mime || "image/png";
        if (!b64) continue;
        const src = String(b64).startsWith("data:") ? String(b64) : ("data:" + mime + ";base64," + b64);
        chartsHtml += '<div class="ask-section"><h4>' + esc(ch.name || COPY.section_charts) + '</h4>' +
          '<div class="ask-chart"><img alt="' + esc(ch.name || "chart") + '" src="' + src.replace(/"/g, "&quot;") + '"/></div></div>';
      }

      let seriesHtml = "";
      for (const s of seriesList) seriesHtml += renderSeriesSvg(s);

      let sectionsHtml = "";
      for (const sec of sections){
        const body = String(sec.body_md || "");
        sectionsHtml += '<div class="ask-section"><h4>' + esc(sec.heading || COPY.section_points) + '</h4>';
        if (body.trim()) sectionsHtml += '<div class="ask-md">' + renderMd(body) + '</div>';
        sectionsHtml += '</div>';
      }

      reportEl.innerHTML =
        '<div class="ask-report-head"><div><h3>' + esc(report.title || "智能分析") + '</h3>' +
        '<div class="ask-meta" style="margin-top:6px">' + esc(COPY.label_trade_day) + ' ' + esc(String(tradeDay)) +
        ' · ' + esc(COPY.label_delay) + ' ' + esc(latency) +
        ' · ' + esc(String(mode)) + '</div></div>' +
        '<span class="ask-badge">' + esc(badge) + '</span></div>' +
        '<div class="ask-summary"><b>' + esc(COPY.section_summary) + '</b><div class="ask-md">' + renderMd(summary) + '</div></div>' +
        chipsHtml + kpisHtml + tableHtml + seriesHtml + chartsHtml + sectionsHtml +
        '<div class="ask-section"><h4>' + esc(COPY.section_risk) + '</h4><ul>' +
        riskLines.map((l) => '<li>' + esc(l) + '</li>').join("") + '</ul></div>' +
        '<div class="ask-disc">' + esc(disclaimer) + '</div>';
      setState("success");
    }
    function showError(code, detail){
      const msg = mapError(code);
      const extra = (detail && detail !== msg ? ' <span class="ask-meta">（' + esc(detail) + '）</span>' : '');
      errorText.innerHTML = '<b>分析失败</b>：' + esc(msg) + extra;
      setState("error");
    }
    async function sleep(ms){ return new Promise((r) => setTimeout(r, ms)); }
    async function fetchJsonWithRetry(url, options, retries){
      let lastErr = null;
      for (let i = 0; i <= retries; i++){
        try {
          const res = await fetch(url, options);
          let data = null;
          try { data = await res.json(); } catch { data = null; }
          return { res, data, networkError: null };
        } catch (err) {
          lastErr = err;
          if (i < retries) await sleep(800 * (i + 1));
        }
      }
      return { res: null, data: null, networkError: lastErr };
    }
    async function pollJobUntilDone(jobId, pollPath){
      const path = pollPath || ("/api/nl-analyze/jobs/" + encodeURIComponent(jobId));
      const deadline = Date.now() + 6 * 60 * 1000; // ≥5–6 min
      while (Date.now() < deadline){
        const { res, data, networkError } = await fetchJsonWithRetry(path, { method: "GET", headers: { "Accept": "application/json" } }, 3);
        if (networkError){
          const name = networkError && networkError.name ? String(networkError.name) : "";
          const msg = String((networkError && networkError.message) || networkError || "");
          if (name === "AbortError") return { kind: "error", code: "error_aborted", detail: msg };
          return { kind: "error", code: "error_network", detail: msg || "轮询连接中断" };
        }
        if (data && data.ok && data.report){
          return { kind: "done", data };
        }
        if (data && data.ok && data.async && (data.status === "queued" || data.status === "running")){
          await sleep(2000);
          continue;
        }
        if (data && data.ok === false){
          const code = data.error && data.error.code ? data.error.code : "error_generic";
          const detail = data.error && data.error.message ? data.error.message : "";
          return { kind: "error", code, detail };
        }
        // Unexpected shape — brief wait then retry until deadline
        await sleep(2000);
      }
      return { kind: "error", code: "error_timeout", detail: "轮询超时（>6 分钟）" };
    }
    async function runAnalyze(){
      const query = (textarea.value || "").trim();
      if (!query){
        textarea.focus();
        setState("empty");
        return;
      }
      setState("loading");
      reportEl.innerHTML = "";
      if (useMock){
        await new Promise((r) => setTimeout(r, 600));
        renderReport(mockReport(), null, { mode: "skill_direct" });
        return;
      }
      try {
        const { res, data, networkError } = await fetchJsonWithRetry("/api/nl-analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, locale: "zh-CN" })
        }, 2);
        if (networkError){
          const name = networkError && networkError.name ? String(networkError.name) : "";
          const msg = String((networkError && networkError.message) || networkError || "");
          if (name === "AbortError") showError("error_aborted", msg);
          else showError("error_network", msg || "客户端连接中断");
          return;
        }
        // Sync legacy path (skill_direct or already-complete)
        if (data && data.ok && data.report){
          renderReport(data.report, data.intent, data.meta);
          return;
        }
        // Async job path
        if (data && data.ok && (data.async || data.job_id) && data.job_id){
          const polled = await pollJobUntilDone(data.job_id, data.poll_path);
          if (polled.kind === "done"){
            renderReport(polled.data.report, polled.data.intent, polled.data.meta);
            return;
          }
          showError(polled.code, polled.detail);
          return;
        }
        const code = data && data.error && data.error.code
          ? data.error.code
          : (res && res.status === 501 ? "pending_harness" : "error_generic");
        const detail = data && data.error && data.error.message ? data.error.message : "";
        showError(code, detail);
      } catch (err){
        const name = err && err.name ? String(err.name) : "";
        const msg = String((err && err.message) || err || "");
        if (name === "AbortError"){
          showError("error_aborted", msg);
        } else if (name === "TypeError" || /Failed to fetch|NetworkError|network|Load failed|fetch/i.test(msg)){
          showError("error_network", msg);
        } else {
          showError("error_network", msg || "客户端连接中断");
        }
      }
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); runAnalyze(); });
    retryBtn.addEventListener("click", () => runAnalyze());
    for (const chip of document.querySelectorAll(".ask-hint")){
      chip.addEventListener("click", () => {
        textarea.value = chip.getAttribute("data-chip") || chip.textContent || "";
        textarea.focus();
      });
    }
    window.addEventListener("pagehide", clearLoadingTimers);
    window.addEventListener("beforeunload", clearLoadingTimers);
    setState("empty");
  })();
  </script>`;
}


function siteNavigation(active: "home" | "heatmap" | "calendar" | "news" | "ask", model?: PickModelKey): string {
  const q = model ? `?model=${model}` : "";
  return `<nav class="site-nav" aria-label="主导航"><a href="/${q}" data-model-link="/"${active === "home" ? ' class="active" aria-current="page"' : ""}>首页</a><a href="/heatmap"${active === "heatmap" ? ' class="active" aria-current="page"' : ""}>热力图</a><a href="/calendar${q}" data-model-link="/calendar"${active === "calendar" ? ' class="active" aria-current="page"' : ""}>观察日历</a><a href="/news"${active === "news" ? ' class="active" aria-current="page"' : ""}>热点财经</a><a href="/ask"${active === "ask" ? ' class="active" aria-current="page"' : ""}>问询</a></nav>`;
}

function footer(): string { return `<footer><span>仅供观察，不构成投资建议。</span><span>巴小卡股市监控 · ${WORKER_BUILD}</span></footer>`; }
function errorState(title: string, message: string): string { return `<main class="center"><div class="error"><p class="eyebrow">巴小卡股市监控</p><h1>${title}</h1><p>${message}</p><a class="back-link" href="/">← 返回列表</a><footer><span>仅供观察，不构成投资建议。</span><span>巴小卡股市监控</span></footer></div></main>`; }

function pageShell(content: string, title = "巴小卡股市监控 · A 股策略选股", description = "A 股策略选股观察。仅供观察，不构成投资建议。"): string {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#090b0d"><meta name="description" content="${escapeHtml(description)}"><meta property="og:title" content="巴小卡股市监控"><meta property="og:description" content="A 股策略选股观察。仅供观察，不构成投资建议。"><meta property="og:type" content="website"><title>${escapeHtml(title)}</title><style>
    :root{color-scheme:dark;--bg:#080b0d;--panel:#11161b;--line:#263039;--muted:#87919b;--text:#f1f4f5;--accent:#6fe3a2;--red:#ff6666}*{box-sizing:border-box}html{background:var(--bg);overflow-x:clip}body{margin:0;min-width:320px;min-height:100vh;overflow-x:clip;color:var(--text);background:radial-gradient(circle at 84% -12%,#163326 0,transparent 34rem),var(--bg);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:14px;line-height:1.5}main{width:min(1120px,calc(100% - 40px));margin:0 auto;padding:72px 0 40px;max-width:100%}.site-nav{display:flex;flex-wrap:wrap;gap:5px;width:max-content;max-width:100%;margin-bottom:32px;padding:4px;border:1px solid var(--line);border-radius:10px;background:#090d10}.site-nav a{display:grid;place-items:center;min-height:44px;min-width:44px;padding:0 14px;border-radius:7px;color:var(--muted);font-size:13px;text-decoration:none}.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;margin-top:16px}.table-scroll .detail-table,.table-scroll table{margin-top:0}.site-nav a:hover{color:#dce3e6;background:#141a1f}.site-nav a.active{color:var(--accent);background:rgba(111,227,162,.1);box-shadow:inset 0 0 0 1px #315d47}.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;border-bottom:1px solid var(--line);padding-bottom:28px}.eyebrow{display:flex;align-items:center;gap:9px;margin:0 0 10px;color:var(--accent);font-size:12px;font-weight:650;letter-spacing:.16em;text-transform:uppercase}.pulse{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px rgba(111,227,162,.09)}h1{margin:0;font-size:clamp(38px,7vw,72px);line-height:.95;letter-spacing:-.055em;font-weight:720}.summary{display:flex;gap:28px;margin:0}.summary div{min-width:64px}.summary dt{color:var(--muted);font-size:11px;letter-spacing:.12em}.summary dd{margin:5px 0 0;font-size:26px;font-variant-numeric:tabular-nums}.meta{display:flex;justify-content:space-between;align-items:center;padding:16px 0 30px;color:var(--muted);font-size:13px}.mode{padding:4px 9px;border:1px solid var(--line);border-radius:999px;color:#aeb7bf;font-size:11px;letter-spacing:.06em}.strategy-list{display:grid;gap:12px}.strategy,.panel{border:1px solid var(--line);border-radius:14px;background:linear-gradient(145deg,rgba(19,24,29,.96),rgba(13,16,20,.96));box-shadow:0 14px 40px rgba(0,0,0,.12)}.strategy{padding:22px}.strategy-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:17px}.strategy-title{display:flex;align-items:center;gap:9px}h2{margin:0;font-size:15px;font-weight:650;letter-spacing:-.01em}.help-toggle{display:grid;place-items:center;width:22px;height:22px;padding:0;border:1px solid #315d47;border-radius:50%;color:var(--accent);background:transparent;font:700 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}.help-toggle:hover,.help-toggle:focus-visible{border-color:var(--accent);outline:none;background:rgba(111,227,162,.08)}.strategy-help{margin:-2px 0 16px;padding:12px 14px;border:1px solid #274036;border-radius:9px;color:#b7c0c6;background:rgba(111,227,162,.045);font-size:12px;line-height:1.65}.strategy-help p{margin:0}.strategy-help p+p{margin-top:5px;color:var(--muted)}.strategy-help strong{color:var(--accent)}.count{display:grid;place-items:center;min-width:31px;height:25px;padding:0 8px;border-radius:7px;color:var(--accent);background:rgba(111,227,162,.08);font:12px ui-monospace,SFMono-Regular,Menlo,monospace}.symbols{display:flex;flex-wrap:wrap;gap:7px}.symbol{display:grid;gap:9px;min-width:min(100%,220px);flex:1 1 220px;padding:10px 12px;border:1px solid #29333b;border-radius:8px;color:#cbd2d8;background:#0b0f12;font:12px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;text-decoration:none}.symbol-id{display:flex;align-items:baseline;gap:9px}.symbol b{color:#f2f5f6;letter-spacing:.04em}.symbol-id>span{overflow:hidden;color:#919ca5;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;text-overflow:ellipsis;white-space:nowrap}.symbol-head{display:grid;gap:6px}.symbol-hits{display:flex;flex-wrap:wrap;gap:4px}.hit-chip{flex:0 0 auto;padding:3px 8px;border:1px solid #315641;border-radius:999px;color:#b8f0d0;background:rgba(111,227,162,.08);font:650 11px/1.2 "PingFang SC",Inter,ui-sans-serif,sans-serif;white-space:nowrap}.symbol-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding-top:8px;border-top:1px solid #202930}.symbol-metrics>span{min-width:0}.symbol-metrics small,.symbol-metrics strong{display:block}.symbol-metrics small{margin-bottom:5px;color:#69737c;font:9px/1 Inter,ui-sans-serif,sans-serif}.symbol-metrics strong{overflow:hidden;color:#eef2f4;font-size:11px;letter-spacing:0;text-overflow:ellipsis}.symbol-metrics strong.positive{color:var(--accent)}.symbol-metrics strong.negative{color:var(--red)}.symbol-metrics strong.neutral{color:var(--muted)}.symbol:hover{border-color:#47705a;color:#fff}.expand-more{display:inline-flex;align-items:center;justify-content:center;min-height:44px;margin-top:4px;padding:0 14px;border:1px dashed #315641;border-radius:8px;color:var(--accent);background:rgba(111,227,162,.06);font:12px Inter,ui-sans-serif,sans-serif;cursor:pointer}.expand-more:hover,.expand-more:focus-visible{border-style:solid;border-color:var(--accent);outline:none;background:rgba(111,227,162,.12)}.empty,.note{color:var(--muted);font-size:13px}footer{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:28px 0 0;color:#59616a;font-size:12px}.center{min-height:100vh;display:grid;place-items:center;padding:24px}.error{max-width:520px;padding:36px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}.error h1{margin-bottom:16px;font-size:34px;letter-spacing:-.03em}.error>p:not(.eyebrow){margin:0 0 28px;color:var(--muted)}.back-link{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;border:1px solid #315641;border-radius:8px;color:var(--accent);text-decoration:none;font-size:13px}.back-link:hover{border-color:var(--accent);color:#fff}
    .detail-page{padding-top:56px}.detail-nav{display:flex;align-items:center;justify-content:space-between;margin-bottom:30px}.stock-head{display:flex;align-items:flex-end;justify-content:space-between;gap:30px;padding:0 0 28px;border-bottom:1px solid var(--line)}.stock-head h1{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:clamp(52px,7vw,70px);font-variant-numeric:tabular-nums;letter-spacing:.08em}.stock-name{display:flex;align-items:center;gap:10px;margin-top:16px;font-size:22px;font-weight:700}.market{padding:4px 8px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:11px;font-weight:400}.quote{text-align:right;font-variant-numeric:tabular-nums}.quote strong{display:block;font-size:29px}.quote span{display:block;margin-top:7px;font-size:14px}.positive{color:var(--accent)}.negative{color:var(--red)}.neutral{color:var(--muted)}.overview-grid{display:grid;grid-template-columns:3fr 2fr;gap:12px;margin-top:22px}.panel{padding:20px}.panel h2{margin-bottom:18px;color:#cdd4da}.company dl{display:grid;gap:9px;margin:0}.company dl div{display:grid;grid-template-columns:90px 1fr;gap:10px}.company dt{color:var(--muted);font-size:13px}.company dd{margin:0;font-size:13px}.note{margin:15px 0 0;font-size:11px}.pick-tags{display:flex;flex-wrap:wrap;gap:7px}.pick-tags>span:not(.empty){padding:7px 10px;border:1px solid #28553f;border-radius:999px;color:var(--accent);background:rgba(111,227,162,.07);font-size:12px}.chart-panel,.report-panel,.reports{margin-top:12px}.chart-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.chart-head h2{margin:0 0 5px}.chart-head p{margin:0;color:var(--muted);font-size:11px}.chart-head>a{color:#69747d;font-size:10px;text-decoration:none}.chart-head>a:hover{color:var(--accent)}.kx-shell{overflow:hidden;border:1px solid #202930;border-radius:10px;background:#090d10}.kx-shell #kx{width:100%;height:360px}.kx-load-error{display:grid;place-items:center;color:var(--muted)}.kx-stats{display:grid;grid-template-columns:1.15fr repeat(5,minmax(0,1fr));gap:8px;padding:10px;border-top:1px solid #202930;background:#090d10;font-variant-numeric:tabular-nums}.kx-stats>span{min-width:0;padding:8px 9px;border:1px solid #202930;border-radius:7px;background:#0b0f12}.kx-stats small,.kx-stats strong{display:block}.kx-stats small{margin-bottom:5px;color:var(--muted);font-size:9px}.kx-stats strong{overflow:hidden;color:#e7ecef;font:600 12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;text-overflow:ellipsis;white-space:nowrap}.kx-stats .kx-date{display:flex;align-items:center;color:#7f8b94;font:11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.chart-empty,.report-empty{display:grid;place-items:center;min-height:110px;color:var(--muted);border:1px solid #202930;border-radius:10px;background:#090d10}.report-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.report-grid>div{padding:13px;border:1px solid #202930;border-radius:9px;background:#0a0e11}.report-grid span{display:block;margin-bottom:7px;color:var(--muted);font-size:11px}.report-grid strong{font-size:18px;font-variant-numeric:tabular-nums}.report-list>div{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:18px;align-items:center;padding:13px 0;border-bottom:1px solid var(--line);font-size:13px}.report-list>div:last-child{border-bottom:0}.report-list span,.report-list time{color:var(--muted)}
    @media(max-width:899px){main{width:min(100% - 40px,1120px)}.masthead,.stock-head{align-items:flex-start;flex-direction:column}.summary{width:100%;flex-wrap:wrap;gap:16px}.overview-grid{grid-template-columns:1fr}.quote{text-align:left}.report-grid{grid-template-columns:1fr}.report-list>div{grid-template-columns:1fr}.chart-head{align-items:flex-start;flex-direction:column;gap:4px}.kx-shell #kx{height:340px}.kx-stats{grid-template-columns:repeat(3,minmax(0,1fr))}.kx-stats .kx-date{grid-column:1/-1}.symbol{min-width:0;flex:1 1 calc(50% - 7px);max-width:100%}.symbols{display:flex;flex-wrap:wrap}}@media(max-width:599px){main{width:min(100% - 28px,1120px);padding-top:36px;padding-bottom:28px}.site-nav{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;width:100%;max-width:100%;scrollbar-width:none}.site-nav::-webkit-scrollbar{display:none}.site-nav a{flex:0 0 auto;min-height:44px;padding:0 16px;font-size:13px}.masthead{gap:16px;padding-bottom:20px}h1{font-size:clamp(32px,10vw,48px)}.summary{flex-direction:column;gap:12px;width:100%}.summary div{min-width:0;width:100%}.summary dd{font-size:22px}.meta{flex-wrap:wrap;gap:10px;align-items:flex-start}.strategy{padding:16px 14px;border-radius:11px}.strategy-head{flex-wrap:wrap;gap:10px}.symbols{gap:8px}.symbol{flex:1 1 100%;min-width:0;max-width:100%}.symbol-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.expand-more{width:100%;min-height:44px}.view-tabs{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;flex-wrap:nowrap}.view-tabs a{flex:1 0 auto;min-height:44px;min-width:72px}.stock-head h1{font-size:clamp(36px,12vw,52px);letter-spacing:.04em}.stock-name{font-size:18px;flex-wrap:wrap}.detail-nav{flex-wrap:wrap;gap:10px;margin-bottom:20px}.back-link{min-height:44px}.kx-shell #kx{height:300px}.kx-stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.kx-stats .kx-date{grid-column:1/-1}.company dl div{grid-template-columns:72px 1fr}footer{flex-direction:column;align-items:flex-start}}
  </style></head><body>${content}<script>(()=>{const buttons=[...document.querySelectorAll(".help-toggle")];for(const button of buttons){button.addEventListener("click",()=>{const opening=button.getAttribute("aria-expanded")!=="true";for(const other of buttons){const panel=document.getElementById(other.getAttribute("aria-controls"));other.setAttribute("aria-expanded","false");other.setAttribute("aria-label","策略说明");if(panel)panel.hidden=true}if(opening){const panel=document.getElementById(button.getAttribute("aria-controls"));button.setAttribute("aria-expanded","true");button.setAttribute("aria-label","收起说明");if(panel)panel.hidden=false}})}const esc=(value)=>String(value).replace(/[&<>"']/g,(ch)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[ch]));const finite=(value)=>typeof value==="number"&&Number.isFinite(value);const price=(value)=>finite(value)?Number(value).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2}):"暂无";const pct=(value,digits)=>{if(!finite(value))return "暂无";return (value>0?"+":value<0?"-":"")+Math.abs(value).toFixed(digits)+"%"};const dir=(value)=>!finite(value)?"":value>0?"positive":value<0?"negative":"neutral";const vol=(value)=>{if(!finite(value))return "暂无";const absolute=Math.abs(value);if(absolute>=100000000)return (value/100000000).toFixed(1).replace(/\.0$/,"")+"亿";if(absolute>=10000)return (value/10000).toFixed(absolute>=10000000?0:1).replace(/\.0$/,"")+"万";return Math.round(value).toLocaleString("zh-CN")};for(const button of document.querySelectorAll(".expand-more")){button.addEventListener("click",()=>{const wrap=button.closest(".symbols");const dataEl=wrap&&wrap.querySelector("script.symbols-more-data");if(!wrap||!dataEl){button.remove();return}let rows=[];try{rows=JSON.parse(dataEl.textContent||"[]")}catch{rows=[]}const frag=document.createDocumentFragment();for(const row of rows){const symbol=String(row[0]??"");const name=String(row[1]??"");const close=row[2],chg=row[3],volume=row[4],volChg=row[5];const quote=price(close);const change=pct(chg,1);const volumeText=vol(volume);const volumeChange=pct(volChg,0);const hits=Array.isArray(row[6])?row[6].map((hit)=>String(hit)):[];const hitsHtml=hits.length?'<span class="symbol-hits">'+hits.map((hit)=>'<span class="hit-chip">'+esc(hit)+"</span>").join("")+"</span>":"";const hitsNote=hits.length?"，策略 "+hits.join("、"):"";const label=name?symbol+" "+name:symbol;const contents='<span class="symbol-head"><span class="symbol-id"><b>'+esc(symbol)+"</b>"+(name?'<span>'+esc(name)+"</span>":"")+'</span>'+hitsHtml+'</span><span class="symbol-metrics"><span><small>收盘</small><strong>'+quote+'</strong></span><span><small>涨跌</small><strong class="'+dir(chg)+'">'+change+'</strong></span><span><small>成交量</small><strong>'+volumeText+'</strong></span><span><small>量涨跌</small><strong class="'+dir(volChg)+'">'+volumeChange+"</strong></span></span>";let node;if(/^\d{6}$/.test(symbol)){node=document.createElement("a");node.className="symbol";node.href="/s/"+symbol;node.setAttribute("aria-label","查看 "+label+" 详情，收盘 "+quote+"，涨跌 "+change+"，成交量 "+volumeText+"，量涨跌 "+volumeChange+hitsNote);node.innerHTML=contents}else{node=document.createElement("span");node.className="symbol";node.innerHTML=contents}frag.append(node)}wrap.insertBefore(frag,button);dataEl.remove();button.remove()})}})()</script></script></body></html>`;
}

function scanDate(data: LatestPicks): string {
  // Prefer an explicit signal day; daily_picks.date is the current producer's signal-day field.
  const candidates: unknown[] = [data.signal_day, data.as_of, data.daily_picks?.date, data.date, data.generated_at];
  for (const value of candidates) {
    if (typeof value !== "string") continue;
    const match = value.match(/^(\d{4}-\d{2}-\d{2})(?:$|T|\s)/);
    if (match) return match[1];
  }
  return "—";
}

function formatShanghaiTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}
function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[character] as string);
}
function html(body: string, status = 200, cacheControl = "no-store"): Response {
  return new Response(body, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": cacheControl, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; connect-src 'self'; img-src data:; base-uri 'none'; frame-ancestors 'none'" } });
}
function json(body: unknown, status = 200, extraHeaders: HeadersInit = {}): Response {
  const headers = new Headers(extraHeaders);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Cache-Control", "no-store");
  headers.set("X-Content-Type-Options", "nosniff");
  return new Response(JSON.stringify(body), { status, headers });
}
function methodNotAllowed(allow: string): Response {
  return new Response("Method Not Allowed", { status: 405, headers: { Allow: allow, "Content-Type": "text/plain; charset=utf-8" } });
}
