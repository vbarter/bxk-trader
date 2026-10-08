/** A-share stock heatmap (self-built treemap, no TradingView) — heatmap-0.11.3
 * - Industry level AND stock level use squarified treemap (desktop L0 / zoom / mobile bands).
 * - ≤899 L0: full multi-industry treemap as vertical flow of industry bands (scrollable, no overlap);
 *   inside each band stocks are squarified.
 * - Long tail per industry → one "其他 N 只" cell (cap-weighted avg pct). Title / 其他 click → zoom.
 * - Text only when cell short side ≥ 28px; logo only when short side ≥ 72px.
 * - Area modes: float (流通市值) | sqrt (√总市值) | total; default from payload.area_default; ?area= overrides.
 */

/* ============================================================================
 * COPY — writer's copy (heatmap-0.11.3). Replace values here to update page text.
 * Placeholders: {date} {time} {n} {name} {code} {pct} {cap}(流通市值, 亿)
 * - meta / meta_sqrt / meta_total: chosen by area mode (float default; sqrt = ?area=sqrt or auto fallback)
 * - note_sqrt: extra line before note, only in sqrt mode
 * - blurb_mobile: only at ≤899px
 * - legend_steps: 9 labels, " / "-separated, left (跌) → right (涨)
 * ========================================================================== */
export const HEATMAP_COPY = {
  title: "A股热力图",
  blurb: "每个格子是一只股票，格子越大，流通市值越大。颜色表示当日涨跌幅，红涨绿跌，颜色越深涨跌越多。点行业标题可以放大，看这个行业的全部股票。",
  blurb_mobile: "上下滑动可以看全部行业。",
  meta: "数据日 {date} · 更新于 {time} · 共 {n} 只 · 格子大小按流通市值",
  meta_sqrt: "数据日 {date} · 更新于 {time} · 共 {n} 只 · 格子大小按总市值开平方",
  meta_total: "数据日 {date} · 更新于 {time} · 共 {n} 只 · 格子大小按总市值",
  legend_down: "跌",
  legend_up: "涨",
  legend_flat: "灰色表示涨跌在 0.5% 以内",
  legend_steps: "-5% / -3% / -1% / -0.5% / 平 / +0.5% / +1% / +3% / +5%",
  other_cell: "其他 {n} 只",
  tooltip: "{name} {code} · 涨跌 {pct} · 流通市值 {cap} 亿",
  note: "格子大小按流通市值计算，也就是能在 A 股市场自由买卖的那部分市值，限售股和 H 股不算在内，所以大银行、石油股不会被放得过大。涨跌幅是当日收盘价相对前一日收盘价，不复权，每个交易日收盘后更新。点格子可以进入个股页。仅供观察，不构成投资建议。",
  note_sqrt: "今天的流通市值数据不全，格子大小改按总市值开平方计算，小盘股的格子会比实际比例大一些。",
} as const;

/** Non-copy UI strings (buttons / states / page meta). Not part of the writer's copy block. */
export const HEATMAP_UI = {
  pageTitleSuffix: " · 巴小卡股市监控",
  eyebrow: "仅供观察 · 非买卖建议",
  footer: "仅供观察，不构成投资建议。",
  loading: "正在加载热力数据…",
  empty: "暂无热力数据",
  loadFailed: "热力数据加载失败",
  backLabel: "← 全部行业",
  listButton: "行业列表 · 辅助",
  listButtonBack: "返回热力",
  zoomHint: "点击放大查看全部个股",
} as const;

/** Short aliases for industry titles when the block is narrow (full name stays in title attr). */
export const INDUSTRY_ALIAS: Record<string, string> = {
  非银金融: "非银", 家用电器: "家电", 纺织服饰: "纺服", 有色金属: "有色", 基础化工: "化工",
  公用事业: "公用", 食品饮料: "食饮", 国防军工: "军工", 建筑装饰: "建筑", 轻工制造: "轻工",
  电力设备: "电设", 医药生物: "医药", 机械设备: "机械", 石油石化: "石化", 交通运输: "交运",
  农林牧渔: "农业", 建筑材料: "建材", 商贸零售: "商贸", 社会服务: "社服", 美容护理: "美护",
  房地产: "地产", 计算机: "计算机", 未分类: "未分类",
};

export type HeatmapStock = {
  code: string;
  name: string;
  short: string;
  chg_pct: number;
  mktcap: number;
  float_mktcap?: number | null;
  logo?: string | null;
  logo_url?: string | null;
};

export type HeatmapIndustry = {
  code: string;
  name: string;
  mktcap: number;
  float_mktcap?: number;
  count: number;
  stocks: HeatmapStock[];
};

export type HeatmapPayload = {
  version?: string;
  generated_at?: string;
  asof: string;
  tz?: string;
  area_default?: "float" | "sqrt" | "total";
  float_coverage?: number;
  mktcap_field?: string;
  mktcap_source?: string;
  chg_source?: string;
  stock_count?: number;
  industry_count?: number;
  logo_coverage?: { with_logo?: number; total?: number; pct?: number };
  industries: HeatmapIndustry[];
};

export function isHeatmapPayload(value: unknown): value is HeatmapPayload {
  if (!value || typeof value !== "object") return false;
  const o = value as Record<string, unknown>;
  if (typeof o.asof !== "string" || !Array.isArray(o.industries)) return false;
  return o.industries.every((ind) => {
    if (!ind || typeof ind !== "object") return false;
    const i = ind as Record<string, unknown>;
    return typeof i.name === "string" && Array.isArray(i.stocks);
  });
}

function esc(s: string): string {
  return String(s).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[ch] as string,
  );
}

/** Color bins (A-share: red up / green down). Keep in sync with colorClass() in the client script. */
const LEGEND_CLASSES = ["d4", "d3", "d2", "d1", "fl", "u1", "u2", "u3", "u4"];

export function heatmapView(navHtml: string, build: string): string {
  const C = HEATMAP_COPY;
  const U = HEATMAP_UI;
  const cfg = JSON.stringify({ copy: C, ui: U, alias: INDUSTRY_ALIAS, build }).replace(/</g, "\\u003c");
  const steps = C.legend_steps.split("/").map((x) => x.trim());
  const legend = LEGEND_CLASSES.map(
    (cls, i) => `<span class="bin"><i class="sw ${cls}"></i><em>${esc(steps[i] || "")}</em></span>`,
  ).join("");
  return `<main class="heatmap-page">
  ${navHtml}
  <div id="hm-l0">
    <p class="eyebrow"><span class="pulse" aria-hidden="true"></span>${esc(U.eyebrow)}</p>
    <h1>${esc(C.title)}</h1>
    <p class="lede">${esc(C.blurb)}</p>
    <p class="lede lede-mobile">${esc(C.blurb_mobile)}</p>
    <div class="toolbar">
      <div class="meta" id="hm-meta">${esc(U.loading)}</div>
      <div class="toolbar-right">
        <button type="button" class="aux-btn" id="hm-list-btn" hidden>${esc(U.listButton)}</button>
        <div class="scale" aria-label="${esc(C.legend_flat)}">
          <div class="scale-row"><span class="scale-end">${esc(C.legend_down)}</span>${legend}<span class="scale-end">${esc(C.legend_up)}</span></div>
          <span class="scale-note">${esc(C.legend_flat)}</span>
        </div>
      </div>
    </div>
    <div class="sec-list" id="hm-sec-list" hidden></div>
    <div class="map" id="hm-map" aria-label="${esc(C.title)}"></div>
  </div>
  <div id="hm-l1" hidden>
    <button type="button" class="hm-back" id="hm-back">${esc(U.backLabel)}</button>
    <h1 class="l1-title" id="hm-l1-title">—</h1>
    <p class="lede" id="hm-l1-lede"></p>
    <div class="map map-l1" id="hm-map-l1"></div>
  </div>
  <div class="tip" id="hm-tip" hidden role="tooltip"></div>
  <div class="note"><p id="hm-note-sqrt" hidden>${esc(C.note_sqrt)}</p><p>${esc(C.note)}</p></div>
  <footer><span>${esc(U.footer)}</span><span>巴小卡股市监控 · ${esc(build)}</span></footer>
</main>
<style>
.heatmap-page{--bg:#090b0d;--line:#222930;--muted:#86909b;--text:#f0f3f5;--accent:#6fe3a2;--mapbg:#0b0e11;
  --flat:#414554;--up1:#7d3f47;--up2:#b3383f;--up3:#d9302f;--up4:#f63538;--dn1:#35664a;--dn2:#2f8f4f;--dn3:#2fb257;--dn4:#30cc5a;
  padding-top:38px;color:var(--text);overflow-x:hidden;max-width:100%}
.heatmap-page .site-nav{margin-bottom:18px}
@media(min-width:900px){main.heatmap-page{width:min(1480px,calc(100% - 40px))}}
.heatmap-page .eyebrow{margin:0 0 8px;color:var(--accent);font:650 12px/1 sans-serif;letter-spacing:.12em;display:flex;align-items:center;gap:8px}
.heatmap-page h1{margin:0 0 6px;font-size:clamp(26px,4vw,36px);letter-spacing:-.03em}
.heatmap-page .l1-title{font-size:clamp(22px,5vw,28px)}
.heatmap-page .lede{margin:0 0 14px;color:var(--muted);font-size:13px;line-height:1.5;max-width:760px}
.heatmap-page .toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;margin-bottom:12px}
.heatmap-page .toolbar-right{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.heatmap-page .meta{color:#6b747d;font-size:12px}
.heatmap-page .aux-btn{min-height:36px;padding:0 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--muted);font:650 11px "PingFang SC",sans-serif;cursor:pointer;-webkit-tap-highlight-color:transparent}
.heatmap-page .aux-btn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.heatmap-page .aux-btn.on{color:var(--accent);border-color:#315641;background:rgba(111,227,162,.08)}
.heatmap-page .scale{display:flex;flex-direction:column;align-items:flex-end;gap:3px;min-width:0;max-width:100%;font:600 10px ui-monospace,Menlo,monospace;color:var(--muted)}
.heatmap-page .scale-row{display:flex;align-items:flex-start;gap:2px;flex-wrap:wrap;max-width:100%}
.heatmap-page .scale-end{align-self:flex-start;line-height:10px;padding:0 4px;font:650 11px/10px "PingFang SC",sans-serif;color:#aeb7bf}
.heatmap-page .scale .bin{display:flex;flex-direction:column;align-items:center;gap:2px;min-width:30px}
.heatmap-page .scale .bin em{font-style:normal;font-size:9px;color:#6b747d;white-space:nowrap}
.heatmap-page .scale .sw{width:30px;height:10px;display:block}
.heatmap-page .scale-note{font:500 11px "PingFang SC",sans-serif;color:#6b747d}
.heatmap-page .lede-mobile{display:none}
.heatmap-page .note p{margin:0}.heatmap-page .note p+p{margin-top:6px}
.heatmap-page .map{position:relative;border:1px solid var(--line);border-radius:12px;padding:8px;background:var(--mapbg);min-height:560px;height:min(76vh,860px);overflow:hidden}
.heatmap-page .map.map-flow{display:flex;flex-direction:column;gap:6px;height:auto;min-height:0;overflow:visible;padding:4px}
.heatmap-page .map-l1{min-height:360px;height:auto}
.heatmap-page .sec{position:absolute;background:var(--mapbg);display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden;box-sizing:border-box}
.heatmap-page .sec.sec-flow{position:relative;left:auto;top:auto;width:100%;flex:0 0 auto;border:1px solid #1a2228;border-radius:8px;padding:3px}
.heatmap-page .sec-title{display:block;width:100%;height:20px;flex:0 0 20px;margin:0;padding:0 4px;border:0;background:transparent;color:#c9d0d6;text-align:left;cursor:pointer;font:650 12px/20px "PingFang SC",sans-serif;white-space:nowrap;overflow:hidden;-webkit-tap-highlight-color:transparent}
.heatmap-page .sec-title:hover{color:#fff;background:rgba(255,255,255,.05)}
.heatmap-page .sec-title:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.heatmap-page .sec-title .p,.heatmap-page .sec-head .p{font-weight:600;margin-left:4px}
.heatmap-page .sec-title .n,.heatmap-page .sec-head .n{color:#59616a;font-weight:500;margin-left:4px}
.heatmap-page .p.up{color:#ff7875}.heatmap-page .p.dn{color:#6fe3a2}.heatmap-page .p.fl{color:#a1aab2;background:none}
.heatmap-page .sec-head{display:flex;align-items:center;gap:2px;width:100%;min-height:44px;padding:0 8px;border:0;border-radius:6px;background:transparent;text-align:left;cursor:pointer;color:#c9d0d6;font:650 13px/1.2 "PingFang SC",sans-serif;-webkit-tap-highlight-color:transparent}
.heatmap-page .sec-head:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.heatmap-page .sec-head:active{background:rgba(111,227,162,.06)}
.heatmap-page .sec-body{position:relative;flex:1;min-height:0;min-width:0;background:var(--mapbg)}
.heatmap-page .cell{position:absolute;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:0 2px;overflow:hidden;cursor:pointer;box-sizing:border-box;border:0;margin:0;color:#fff;text-decoration:none;font:inherit;-webkit-tap-highlight-color:transparent}
.heatmap-page .cell:hover{filter:brightness(1.18)}
.heatmap-page .cell:focus-visible{outline:2px solid #fff;outline-offset:-2px}
.heatmap-page .cell .nm,.heatmap-page .cell .pc{color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.4);text-align:center;white-space:nowrap;line-height:1.1;max-width:100%;overflow:hidden;text-overflow:ellipsis}
.heatmap-page .cell .nm{font-weight:650;font-family:"PingFang SC","Microsoft YaHei",sans-serif}
.heatmap-page .cell .pc{font-weight:600;font-family:ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums;opacity:.95}
.heatmap-page .cell.other{box-shadow:inset 0 0 0 1px rgba(255,255,255,.22);background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.06) 0 4px,transparent 4px 9px)}
.heatmap-page .logo{border-radius:50%;background:#fff;display:grid;place-items:center;flex-shrink:0;overflow:hidden;color:#222;font:720 11px/1 "PingFang SC",sans-serif}
.heatmap-page .logo img{width:100%;height:100%;object-fit:cover;display:block}
.heatmap-page .u4{background-color:var(--up4)}.heatmap-page .u3{background-color:var(--up3)}.heatmap-page .u2{background-color:var(--up2)}.heatmap-page .u1{background-color:var(--up1)}
.heatmap-page .d4{background-color:var(--dn4)}.heatmap-page .d3{background-color:var(--dn3)}.heatmap-page .d2{background-color:var(--dn2)}.heatmap-page .d1{background-color:var(--dn1)}
.heatmap-page .fl{background-color:var(--flat)}
.heatmap-page .tip{position:fixed;z-index:40;pointer-events:none;max-width:280px;padding:10px 12px;border-radius:8px;border:1px solid #2a3338;background:rgba(12,16,20,.96);color:#e8eef2;font-size:12px;line-height:1.5;box-shadow:0 8px 24px rgba(0,0,0,.35)}
.heatmap-page .tip b{font:650 13px "PingFang SC",sans-serif;color:#fff}
.heatmap-page .tip .cd{font:600 11px ui-monospace,Menlo,monospace;color:#86909b;margin-left:6px}
.heatmap-page .tip .row{display:flex;justify-content:space-between;gap:12px;color:#aeb7bf}
.heatmap-page .tip .up{color:#ff7875}.heatmap-page .tip .dn{color:#6fe3a2}.heatmap-page .tip .fl{color:#a1aab2;background:none}
.heatmap-page .tip .hint{margin-top:4px;color:#6b747d;font-size:11px}
.heatmap-page .tip .hd{font:650 13px "PingFang SC",sans-serif;color:#fff}
.heatmap-page .note{margin-top:14px;padding:12px 14px;border-radius:10px;border:1px solid #2a3338;background:#0c1014;color:#aeb7bf;font-size:12px;line-height:1.55}
.heatmap-page .note b{color:#e8eef2}
.heatmap-page .empty{display:grid;place-items:center;min-height:420px;color:var(--muted);font-size:13px}
.heatmap-page .sec-list{display:grid;gap:8px;margin-bottom:12px}
.heatmap-page .sec-card{display:flex;align-items:center;gap:10px;min-height:52px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#0a0c0f;color:inherit;cursor:pointer;width:100%;font:inherit;text-align:left;-webkit-tap-highlight-color:transparent}
.heatmap-page .sec-card:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.heatmap-page .sec-card .swatch{width:36px;height:36px;border-radius:8px;flex-shrink:0}
.heatmap-page .sec-card .t{flex:1;min-width:0}.heatmap-page .sec-card .t b{display:block;font-size:14px;font-weight:650}.heatmap-page .sec-card .t span{color:var(--muted);font-size:12px}
.heatmap-page .sec-card .rpct{font:650 13px ui-monospace,Menlo,monospace;flex-shrink:0}
.heatmap-page .sec-card .rpct.up{color:#ff7875}.heatmap-page .sec-card .rpct.dn{color:#6fe3a2}.heatmap-page .sec-card .rpct.fl{color:#59616a;background:none}
.heatmap-page .hm-back{display:inline-flex;align-items:center;gap:6px;min-height:44px;margin:0 0 8px;padding:0 8px;border:0;background:transparent;color:var(--accent);font:650 13px/1 "PingFang SC",sans-serif;cursor:pointer}
.heatmap-page .hm-back:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
@media(max-width:899px){
  .heatmap-page{padding-top:28px}
  .heatmap-page .lede{font-size:12px}
  .heatmap-page .aux-btn{min-height:44px}
  .heatmap-page .lede-mobile{display:block;margin-top:-8px}
  .heatmap-page .toolbar-right{width:100%;justify-content:flex-start}
  .heatmap-page .scale{align-items:flex-start}
  .heatmap-page .scale .bin{min-width:26px}.heatmap-page .scale .sw{width:26px}
}
@media(max-width:599px){
  .heatmap-page h1{font-size:clamp(22px,8vw,28px)}
  .heatmap-page .sec-card{min-height:48px;padding:10px;gap:8px}
  .heatmap-page .sec-card .t span{font-size:11px}
  .heatmap-page .note{font-size:11px;padding:10px 12px}
  .heatmap-page .map-l1{border-radius:10px;padding:4px}
  .heatmap-page .site-nav{flex-wrap:wrap;overflow:visible;width:auto;max-width:100%;gap:3px}
  .heatmap-page .site-nav a{flex:0 0 auto;padding:0 10px}
  .heatmap-page .scale .bin{min-width:0;flex:1 1 0}.heatmap-page .scale .sw{width:100%;min-width:20px}
  .heatmap-page .scale-row{flex-wrap:nowrap;width:100%}
}
</style>
<script>
(() => {
  const CFG = ${cfg};
  const COPY = CFG.copy;
  const UI = CFG.ui;
  const ALIAS = CFG.alias || {};
  function fill(tpl, vars) {
    return String(tpl).replace(/\\{(\\w+)\\}/g, (m, k) => (vars[k] != null ? String(vars[k]) : m));
  }
  const GAP = 1;            // 1px stroke between stock cells
  const SEC_GAP = 3;        // gap between industry blocks (desktop)
  const TITLE_H = 20;       // desktop industry title bar
  const TEXT_MIN = 28;      // text only when cell short side >= 28
  const LOGO_MIN = 72;      // logo only when cell short side >= 72
  const SEC_MIN_W = 60;     // industry block min width (title must fit)
  const SEC_MIN_H = 50;
  const L0_MIN_SIDE = 12;       // only stocks whose cell short side < 12px merge into 其他
  const L0_MIN_AREA = 12 * 12;  // first-pass estimate (area); squarify pass then enforces L0_MIN_SIDE
  const L0_MAX_CELLS = 600;
  let LAYOUT_MIN_SIDE = 12;
  const HEAD_H = 44;
  const MIN_BAND_BODY = 120;
  const MAX_BAND_BODY = 480;
  const BAND_SUM_RATIO = 10;   // mobile: sum of band bodies ≈ W × this
  const DESK_H_RATIO = 1.05;   // desktop map height ≈ width × this (capped)
  const DESK_H_MAX = 1600;
  const IND_FLOOR_PER_STOCK = 110; // desktop: industry block area floor ≈ stock count × this px² (0 = purely proportional)
  const $ = (id) => document.getElementById(id);
  const metaEl = $("hm-meta"), mapEl = $("hm-map"), mapL1El = $("hm-map-l1"), listEl = $("hm-sec-list"),
    tipEl = $("hm-tip"), l0El = $("hm-l0"), l1El = $("hm-l1"), backEl = $("hm-back"),
    l1Title = $("hm-l1-title"), l1Lede = $("hm-l1-lede"), listBtn = $("hm-list-btn");
  if (!metaEl || !mapEl || !mapL1El || !listEl || !tipEl || !l0El || !l1El || !backEl || !l1Title || !l1Lede || !listBtn) return;

  let payload = null;
  let activeInd = null;
  let listMode = false;
  let cachedIndustries = [];
  let areaMode = "float";
  const measureCtx = document.createElement("canvas").getContext("2d");
  const FONT_CN = '"PingFang SC","Microsoft YaHei",sans-serif';
  const FONT_MONO = "ui-monospace,Menlo,monospace";

  function textW(text, font) {
    if (!measureCtx) return String(text).length * 12;
    measureCtx.font = font;
    return measureCtx.measureText(text).width;
  }
  function isNarrow() { return window.matchMedia("(max-width:899px)").matches; }
  function isNum(v) { return typeof v === "number" && Number.isFinite(v); }

  function fmtCap(v) {
    if (!isNum(v) || v <= 0) return "—";
    if (v >= 1e12) return (v / 1e12).toFixed(2) + " 万亿";
    if (v >= 1e8) return (v / 1e8).toFixed(v >= 1e10 ? 0 : 1) + " 亿";
    if (v >= 1e4) return (v / 1e4).toFixed(0) + " 万";
    return String(Math.round(v));
  }
  function fmtPct(v) {
    if (!isNum(v)) return "—";
    const sign = v > 0 ? "+" : v < 0 ? "−" : "";
    return sign + Math.abs(v).toFixed(2) + "%";
  }
  function dirClass(v) { return !isNum(v) || Math.abs(v) < 0.005 ? "fl" : v > 0 ? "up" : "dn"; }
  /** Bins: |pct|<0.5 flat gray; 0.5–1; 1–3; 3–5; ≥5 (red up / green down). */
  function colorClass(chg) {
    if (!isNum(chg)) return "fl";
    const a = Math.abs(chg);
    if (a < 0.5) return "fl";
    const tier = a < 1 ? 1 : a < 3 ? 2 : a < 5 ? 3 : 4;
    return (chg > 0 ? "u" : "d") + tier;
  }
  function colorVar(chg) {
    const c = colorClass(chg);
    if (c === "fl") return "var(--flat)";
    return "var(--" + (c[0] === "u" ? "up" : "dn") + c[1] + ")";
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[ch]);
  }
  function logoUrlOf(stock) {
    const u = stock && (stock.logo_url || stock.logo);
    return typeof u === "string" && u && u !== "null" ? u : "";
  }

  function areaVal(s) {
    const t = Math.max(Number(s.mktcap) || 0, 0);
    if (areaMode === "sqrt") return Math.sqrt(t);
    if (areaMode === "total") return t;
    const f = Number(s.float_mktcap);
    return f > 0 ? f : t;
  }
  function capWeightedChg(stocks) {
    let num = 0, den = 0;
    for (const s of stocks) {
      if (!isNum(s.chg_pct)) continue;
      const w = Math.max(Number(s.mktcap) || 0, 1);
      num += s.chg_pct * w; den += w;
    }
    return den > 0 ? num / den : 0;
  }
  function indStats(ind) {
    if (ind._mode !== areaMode) {
      ind._mode = areaMode;
      ind._v = (ind.stocks || []).reduce((a, s) => a + areaVal(s), 0) || 1;
      ind._chg = capWeightedChg(ind.stocks || []);
      ind._cap = (ind.stocks || []).reduce((a, s) => a + (Number(s.mktcap) || 0), 0);
    }
    return ind;
  }

  /** Squarified treemap (Bruls et al.). keepOrder: don't re-sort (used to pin 其他 last). */
  function squarify(items, x, y, w, h, keepOrder) {
    const out = [];
    if (!items.length || w <= 0 || h <= 0) return out;
    const nodes = items.filter((it) => it.value > 0);
    if (!keepOrder) nodes.sort((a, b) => b.value - a.value);
    if (!nodes.length) return out;
    let remTotal = nodes.reduce((s, it) => s + it.value, 0);
    const scale = (w * h) / remTotal;
    function worst(row, len) {
      if (!row.length || !(len > 0)) return Infinity;
      let s = 0, max = 0, min = Infinity;
      for (const r of row) { const a = r.value * scale; s += a; if (a > max) max = a; if (a < min) min = a; }
      const s2 = s * s, len2 = len * len;
      return Math.max((len2 * max) / s2, s2 / (len2 * min));
    }
    let remaining = nodes.slice();
    let cx = x, cy = y, cw = w, ch = h;
    while (remaining.length) {
      const horizontal = cw >= ch;
      const side = horizontal ? ch : cw;
      const row = [];
      while (remaining.length) {
        const trial = row.concat([remaining[0]]);
        if (row.length && worst(trial, side) > worst(row, side)) break;
        row.push(remaining.shift());
      }
      const rowSum = row.reduce((a, b) => a + b.value, 0);
      if (!(rowSum > 0) || !(remTotal > 0)) break;
      const last = !remaining.length;
      if (horizontal) {
        const rowW = last ? cw : Math.min(cw, (rowSum / remTotal) * cw);
        let yy = cy;
        for (let i = 0; i < row.length; i++) {
          const hh = i === row.length - 1 ? Math.max(0, cy + ch - yy) : (row[i].value / rowSum) * ch;
          out.push({ item: row[i], x: cx, y: yy, w: rowW, h: hh });
          yy += hh;
        }
        cx += rowW; cw = Math.max(0, cw - rowW);
      } else {
        const rowH = last ? ch : Math.min(ch, (rowSum / remTotal) * ch);
        let xx = cx;
        for (let i = 0; i < row.length; i++) {
          const ww = i === row.length - 1 ? Math.max(0, cx + cw - xx) : (row[i].value / rowSum) * cw;
          out.push({ item: row[i], x: xx, y: cy, w: ww, h: rowH });
          xx += ww;
        }
        cy += rowH; ch = Math.max(0, ch - rowH);
      }
      remTotal -= rowSum;
    }
    return out;
  }

  /** Squarify shown stocks (largest first) with one 其他 item pinned last → 其他 ends bottom-right.
   * Falls back to free ordering (mirrored so 其他 still sits bottom-right) when that packs better. */
  function layoutWithOther(shown, rest, w, h) {
    const items = shown.map((s) => ({ value: areaVal(s), stock: s }));
    const rv = rest.reduce((a, s) => a + areaVal(s), 0);
    if (!rest.length || !(rv > 0)) return squarify(items, 0, 0, w, h, false);
    const all = items.slice().sort((a, b) => b.value - a.value).concat([{ value: rv, other: rest }]);
    const pinned = squarify(all, 0, 0, w, h, true);
    const thin = (laid) => laid.filter((n) => n.item.stock && Math.min(n.w, n.h) - GAP < LAYOUT_MIN_SIDE).length;
    const tp = thin(pinned);
    if (!tp) return pinned;
    const free = squarify(all, 0, 0, w, h, false);
    if (thin(free) >= tp) return pinned;
    if (free.length > 1 && free[0].item.other) {
      for (const n of free) { n.x = w - n.x - n.w; n.y = h - n.y - n.h; }
    }
    return free;
  }

  /** Top stocks get own cells; stocks whose cell short side < minSide merge into one 其他 N 只 cell (pinned last). */
  function packStocks(stocks, w, h, opt) {
    const minArea = opt.minArea, minSide = opt.minSide, maxCells = opt.maxCells;
    LAYOUT_MIN_SIDE = minSide;
    const sorted = stocks.slice().sort((a, b) => areaVal(b) - areaVal(a));
    const total = sorted.reduce((s, x) => s + areaVal(x), 0);
    if (!(total > 0) || w < 2 || h < 2) return [];
    const k = (w * h) / total;
    let shown = [];
    const rest0 = [];
    for (const s of sorted) {
      if (shown.length < maxCells && areaVal(s) * k >= minArea) shown.push(s); else rest0.push(s);
    }
    let rest = rest0;
    if (rest.length === 1) { shown.push(rest[0]); rest = []; }
    let laid = [];
    for (let iter = 0; iter < 40; iter++) {
      laid = layoutWithOther(shown, rest, w, h);
      const bad = [];
      for (const node of laid) {
        if (node.item.stock && Math.min(node.w, node.h) - GAP < minSide) bad.push(node.item.stock);
      }
      if (!bad.length) break;
      // Move only the smallest ~third of the too-thin stocks into 其他, then re-layout (others grow).
      bad.sort((x, y) => areaVal(x) - areaVal(y));
      const moveN = iter >= 30 ? bad.length : Math.max(1, Math.ceil(bad.length / 3));
      const move = new Set(bad.slice(0, moveN));
      shown = shown.filter((s) => !move.has(s));
      if (!shown.length) { const back = bad[bad.length - 1]; shown = [back]; move.delete(back); }
      rest = Array.from(move).concat(rest).sort((x, y) => areaVal(y) - areaVal(x));
    }
    return laid;
  }

  function fitTitle(ind, width) {
    const st = indStats(ind);
    const full = ind.name, alias = ALIAS[ind.name] || ind.name;
    const pct = fmtPct(st._chg), cnt = String(ind.count || ind.stocks.length);
    const fN = "650 12px " + FONT_CN, fP = "600 12px " + FONT_CN, fC = "500 12px " + FONT_CN;
    const avail = width - 10;
    const cands = [[full, true, true], [full, true, false], [full, false, false], [alias, true, false], [alias, false, false]];
    for (const c of cands) {
      let wNeed = textW(c[0], fN);
      if (c[1]) wNeed += 4 + textW(pct, fP);
      if (c[2]) wNeed += 4 + textW(cnt + "只", fC);
      if (wNeed <= avail) return { label: c[0], pct: c[1], cnt: c[2] };
    }
    return { label: alias, pct: false, cnt: false };
  }

  function titleHtml(ind, t) {
    const st = indStats(ind);
    return escapeHtml(t.label) +
      (t.pct ? '<span class="p ' + dirClass(st._chg) + '">' + fmtPct(st._chg) + "</span>" : "") +
      (t.cnt ? '<span class="n">' + (ind.count || ind.stocks.length) + "只</span>" : "");
  }
  function titleAttr(ind) {
    const st = indStats(ind);
    return ind.name + " · " + (ind.count || ind.stocks.length) + " 只 · " + fmtPct(st._chg) + " · " + UI.zoomHint;
  }

  function showTip(html, evt) { tipEl.innerHTML = html; tipEl.hidden = false; moveTip(evt); }
  function fmtYi(v) {
    if (!isNum(v) || v <= 0) return "—";
    const y = v / 1e8;
    return y >= 100 ? Math.round(y).toLocaleString("zh-CN") : y.toFixed(y >= 10 ? 1 : 2);
  }
  /** Tooltip from COPY.tooltip; " · " segments become lines (first line = headline). */
  function stockTip(s) {
    const cls = dirClass(s.chg_pct);
    const txt = fill(COPY.tooltip, {
      name: "\\u0001" + s.name + "\\u0002", code: s.code, pct: "\\u0003" + fmtPct(s.chg_pct) + "\\u0004",
      cap: fmtYi(s.float_mktcap),
    });
    return txt.split(" · ").map((seg, i) => {
      const h = escapeHtml(seg)
        .replace("\\u0001", "<b>").replace("\\u0002", "</b>")
        .replace("\\u0003", '<span class="' + cls + '">').replace("\\u0004", "</span>");
      return i === 0 ? '<div class="hd">' + h + "</div>" : "<div>" + h + "</div>";
    }).join("");
  }
  function otherTip(rest, indName, zoomable) {
    const chg = capWeightedChg(rest);
    const cap = rest.reduce((a, s) => a + (Number(s.mktcap) || 0), 0);
    const top = rest.slice(0, 5).map((s) => escapeHtml(s.name) + " " + fmtPct(s.chg_pct)).join("、");
    return "<b>" + escapeHtml(indName) + " · " + escapeHtml(fill(COPY.other_cell, { n: rest.length })) + "</b>" +
      '<div class="row"><span>市值加权涨跌</span><span class="' + dirClass(chg) + '">' + fmtPct(chg) + "</span></div>" +
      '<div class="row"><span>合计总市值</span><span>' + fmtCap(cap) + "</span></div>" +
      '<div class="hint">' + top + (rest.length > 5 ? " …" : "") + "</div>" +
      (zoomable ? '<div class="hint">' + UI.zoomHint + "</div>" : "");
  }
  function moveTip(evt) {
    const pad = 14;
    const cx = evt && evt.clientX != null ? evt.clientX : 0;
    const cy = evt && evt.clientY != null ? evt.clientY : 0;
    let left = cx + pad, top = cy + pad;
    const rect = tipEl.getBoundingClientRect();
    if (left + rect.width > window.innerWidth - 8) left = cx - rect.width - pad;
    if (top + rect.height > window.innerHeight - 8) top = cy - rect.height - pad;
    tipEl.style.left = Math.max(8, left) + "px";
    tipEl.style.top = Math.max(8, top) + "px";
  }
  function hideTip() { tipEl.hidden = true; }
  function bindTip(el, htmlFn) {
    el.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") showTip(htmlFn(), e); });
    el.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse" && !tipEl.hidden) moveTip(e); });
    el.addEventListener("pointerleave", hideTip);
    el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); showTip(htmlFn(), { clientX: r.left, clientY: r.bottom }); });
    el.addEventListener("blur", hideTip);
  }

  function appendLogo(parent, stock, size) {
    const logo = document.createElement("div");
    logo.className = "logo";
    logo.style.width = size + "px";
    logo.style.height = size + "px";
    logo.style.fontSize = Math.max(9, Math.round(size * 0.42)) + "px";
    const short = stock.short || (stock.name && stock.name[0]) || "?";
    const url = logoUrlOf(stock);
    if (url) {
      const img = document.createElement("img");
      img.alt = ""; img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
      img.src = url;
      img.onerror = function () { img.remove(); logo.textContent = short; };
      logo.appendChild(img);
    } else {
      logo.textContent = short;
    }
    parent.appendChild(logo);
  }

  /** Label: 简称 + 涨跌幅 when it fits; pct only when name won't fit; nothing below 28px short side. */
  function labelCell(el, names, pctText, w, h, logoStock) {
    const side = Math.min(w, h);
    if (side < TEXT_MIN) return;
    if (!Array.isArray(names)) names = [names];
    for (const name of names) {
      if (labelTry(el, name, pctText, w, h, logoStock, side)) return;
    }
    for (let pfs = Math.max(10, Math.min(16, Math.round(side / 3.2))); pfs >= 9; pfs--) {
      if (textW(pctText, "600 " + pfs + "px " + FONT_MONO) <= w - 8 && h >= pfs + 4) {
        el.insertAdjacentHTML("beforeend", '<div class="pc" style="font-size:' + pfs + 'px">' + escapeHtml(pctText) + "</div>");
        return;
      }
    }
  }
  function labelTry(el, name, pctText, w, h, logoStock, side) {
    let fs = Math.max(10, Math.min(22, Math.round(side / 4)));
    for (; fs >= 10; fs--) {
      const pfs = Math.max(9, Math.round(fs * 0.82));
      const nameOk = textW(name, "650 " + fs + "px " + FONT_CN) * 1.08 <= w - 8;
      const pctOk = textW(pctText, "600 " + pfs + "px " + FONT_MONO) <= w - 8;
      if (nameOk && pctOk && h >= fs * 1.1 + pfs * 1.1 + 6) {
        const logoSize = Math.max(20, Math.min(40, Math.round(side * 0.3)));
        if (logoStock && side >= LOGO_MIN && h >= logoSize + fs * 1.1 + pfs * 1.1 + 12) appendLogo(el, logoStock, logoSize);
        el.insertAdjacentHTML("beforeend",
          '<div class="nm" style="font-size:' + fs + 'px">' + escapeHtml(name) + "</div>" +
          '<div class="pc" style="font-size:' + pfs + 'px">' + escapeHtml(pctText) + "</div>");
        return true;
      }
    }
    return false;
  }

  function drawStocks(body, ind, stocks, width, height, opt) {
    body.innerHTML = "";
    if (!(width > 2 && height > 2) || !stocks.length) return;
    const laid = packStocks(stocks, width, height, opt);
    const frag = document.createDocumentFragment();
    for (const node of laid) {
      const x = node.x, y = node.y;
      const w = Math.max(0, node.w - GAP), h = Math.max(0, node.h - GAP);
      if (w < 1 || h < 1) continue;
      let el;
      if (node.item.stock) {
        const s = node.item.stock;
        el = document.createElement("a");
        el.className = "cell " + colorClass(s.chg_pct);
        el.href = "/s/" + s.code;
        el.setAttribute("aria-label", s.name + " " + s.code + " " + fmtPct(s.chg_pct));
        labelCell(el, s.name, fmtPct(s.chg_pct), w, h, s);
        bindTip(el, () => stockTip(s));
      } else {
        const rest = node.item.other;
        const chg = capWeightedChg(rest);
        el = document.createElement(opt.zoomable ? "button" : "div");
        if (opt.zoomable) el.type = "button";
        el.className = "cell other " + colorClass(chg);
        const otherLabel = fill(COPY.other_cell, { n: rest.length });
        el.setAttribute("aria-label", ind.name + " " + otherLabel + " " + fmtPct(chg));
        labelCell(el, [otherLabel, otherLabel.replace(/\\s+/g, ""), "+" + rest.length], fmtPct(chg), w, h, null);
        if (!el.childNodes.length && Math.min(w, h) >= 16 && w >= textW("+" + rest.length, "600 10px " + FONT_MONO) + 8) {
          el.insertAdjacentHTML("beforeend", '<div class="pc" style="font-size:10px">+' + rest.length + "</div>");
        }
        if (opt.zoomable) el.addEventListener("click", () => openIndustry(ind.name));
        bindTip(el, () => otherTip(rest, ind.name, opt.zoomable));
      }
      el.style.left = x + "px"; el.style.top = y + "px";
      el.style.width = w + "px"; el.style.height = h + "px";
      frag.appendChild(el);
    }
    body.appendChild(frag);
  }

  const L0_OPT = { minArea: L0_MIN_AREA, minSide: L0_MIN_SIDE, maxCells: L0_MAX_CELLS, zoomable: true };

  /** Squarify industries with an area floor so every block holds its title (min width/height). */
  function layoutIndustries(industries, W, H) {
    const vals = industries.map((ind) => indStats(ind)._v);
    const total = vals.reduce((a, b) => a + b, 0) || 1;
    let floorArea = SEC_MIN_W * SEC_MIN_H * 1.2;
    let best = null;
    for (let iter = 0; iter < 10; iter++) {
      const pxToV = total / (W * H);
      const items = industries.map((ind, i) => ({
        value: Math.max(vals[i], floorArea * pxToV, (ind.stocks || []).length * IND_FLOOR_PER_STOCK * pxToV),
        ind: ind,
      }));
      const laid = squarify(items, 0, 0, W, H, false);
      const bad = laid.filter((n) => n.w - SEC_GAP < SEC_MIN_W || n.h - SEC_GAP < SEC_MIN_H).length;
      if (!best || bad < best.bad) best = { laid: laid, bad: bad };
      if (!bad) break;
      floorArea *= 1.35;
    }
    return best ? best.laid : [];
  }

  function renderDesktop(industries) {
    listMode = false;
    listBtn.hidden = true;
    listBtn.classList.remove("on");
    listEl.hidden = true;
    listEl.innerHTML = "";
    mapEl.hidden = false;
    mapEl.classList.remove("map-flow");
    mapEl.style.minHeight = "";
    mapEl.innerHTML = "";
    // Taller-than-viewport map (page scrolls) so long tails fit as ≥12px cells instead of a giant 其他.
    const mw = mapEl.getBoundingClientRect().width;
    mapEl.style.height = Math.round(Math.max(560, window.innerHeight * 0.76, Math.min(mw * DESK_H_RATIO, DESK_H_MAX))) + "px";
    const rect = mapEl.getBoundingClientRect();
    const W = Math.max(320, rect.width - 18) + SEC_GAP;
    const H = Math.max(420, rect.height - 18) + SEC_GAP;
    const laid = layoutIndustries(industries, W, H);
    for (const node of laid) {
      const x = node.x + 8, y = node.y + 8;
      const w = Math.max(0, node.w - SEC_GAP), h = Math.max(0, node.h - SEC_GAP);
      if (w < 8 || h < 8) continue;
      const ind = node.item.ind;
      const sec = document.createElement("section");
      sec.className = "sec";
      sec.style.left = x + "px"; sec.style.top = y + "px";
      sec.style.width = w + "px"; sec.style.height = h + "px";
      const title = document.createElement("button");
      title.type = "button";
      title.className = "sec-title";
      title.title = titleAttr(ind);
      title.innerHTML = titleHtml(ind, fitTitle(ind, w));
      title.addEventListener("click", () => openIndustry(ind.name));
      sec.appendChild(title);
      const body = document.createElement("div");
      body.className = "sec-body";
      sec.appendChild(body);
      mapEl.appendChild(sec);
      const bw = Math.floor(body.clientWidth || w), bh = Math.floor(body.clientHeight || Math.max(0, h - TITLE_H));
      drawStocks(body, ind, ind.stocks, bw + GAP, bh + GAP, L0_OPT);
    }
  }

  /** Narrow L0: vertical flow of industry bands (full treemap, no overlap); squarified inside each band. */
  function renderNarrowBands(industries) {
    listEl.hidden = true;
    listEl.innerHTML = "";
    listBtn.hidden = false;
    listBtn.classList.toggle("on", listMode);
    listBtn.textContent = listMode ? UI.listButtonBack : UI.listButton;
    if (listMode) {
      mapEl.hidden = true;
      mapEl.innerHTML = "";
      mapEl.classList.remove("map-flow");
      renderAuxList(industries);
      return;
    }
    mapEl.hidden = false;
    mapEl.classList.add("map-flow");
    mapEl.style.height = "auto";
    mapEl.style.minHeight = "0";
    mapEl.innerHTML = "";
    const rect = mapEl.getBoundingClientRect();
    const W = Math.max(280, Math.floor(rect.width - 10)); // content width (border 1+1, padding 4+4)
    const total = industries.reduce((s, ind) => s + indStats(ind)._v, 0) || 1;
    const TARGET_BODY_SUM = Math.max(3200, Math.round(W * BAND_SUM_RATIO));
    for (const ind of industries) {
      const share = indStats(ind)._v / total;
      const bodyH = Math.max(MIN_BAND_BODY, Math.min(MAX_BAND_BODY, Math.round(share * TARGET_BODY_SUM)));
      const sec = document.createElement("section");
      sec.className = "sec sec-flow";
      sec.style.height = HEAD_H + bodyH + 8 + "px";
      const head = document.createElement("button");
      head.type = "button";
      head.className = "sec-head";
      head.title = titleAttr(ind);
      head.innerHTML = titleHtml(ind, { label: ind.name, pct: true, cnt: true });
      head.setAttribute("aria-label", UI.zoomHint + " " + ind.name);
      head.addEventListener("click", () => openIndustry(ind.name));
      sec.appendChild(head);
      const body = document.createElement("div");
      body.className = "sec-body";
      body.style.height = bodyH + "px";
      body.style.flex = "0 0 auto";
      sec.appendChild(body);
      mapEl.appendChild(sec);
      // Lay out in the band body's own content box (card padding/border already excluded).
      const bw = Math.floor(body.clientWidth || body.getBoundingClientRect().width || (W - 8));
      drawStocks(body, ind, ind.stocks, bw + GAP, bodyH + GAP, L0_OPT);
    }
  }

  /** Auxiliary industry list (not default L0). */
  function renderAuxList(industries) {
    listEl.hidden = false;
    listEl.innerHTML = "";
    for (const ind of industries) {
      const st = indStats(ind);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sec-card";
      btn.innerHTML =
        '<i class="swatch" style="background:' + colorVar(st._chg) + '" aria-hidden="true"></i>' +
        '<div class="t"><b>' + escapeHtml(ind.name) + "</b><span>" +
        (ind.count || ind.stocks.length) + " 只 · 总市值 " + fmtCap(st._cap) + "</span></div>" +
        '<span class="rpct ' + dirClass(st._chg) + '">' + fmtPct(st._chg) + "</span>";
      btn.addEventListener("click", () => openIndustry(ind.name));
      listEl.appendChild(btn);
    }
  }

  /** Zoom: single industry, all stocks, squarified; height grows with stock count. */
  function renderL1(ind) {
    const st = indStats(ind);
    l1Title.textContent = ind.name;
    l1Lede.textContent = (ind.count || ind.stocks.length) + " 只 · 总市值 " + fmtCap(st._cap) +
      " · 市值加权 " + fmtPct(st._chg);
    l0El.hidden = true;
    l1El.hidden = false;
    mapL1El.innerHTML = "";
    requestAnimationFrame(() => {
      const narrow = isNarrow();
      const rect = mapL1El.getBoundingClientRect();
      const pad = narrow ? 8 : 16;
      const W = Math.max(200, Math.floor(mapL1El.clientWidth - pad));
      const base = narrow ? Math.max(360, window.innerHeight * 0.7) : Math.max(520, Math.min(860, window.innerHeight * 0.76));
      const vals = ind.stocks.map(areaVal).sort((a, b) => b - a);
      const total = vals.reduce((a, b) => a + b, 0) || 1;
      const v70 = vals[Math.floor(vals.length * 0.7)] || vals[vals.length - 1] || 1;
      const need = ((total / v70) * 30 * 30) / W;
      const H = Math.round(Math.max(base, Math.min(narrow ? 4200 : 3000, need)));
      mapL1El.style.height = H + pad + 2 + "px";
      const body = document.createElement("div");
      body.className = "sec-body";
      body.style.position = "absolute";
      body.style.left = pad / 2 + "px"; body.style.top = pad / 2 + "px";
      body.style.width = W + "px"; body.style.height = H + "px";
      mapL1El.appendChild(body);
      drawStocks(body, ind, ind.stocks, W + GAP, H + GAP, { minArea: 0, minSide: 2, maxCells: Infinity, zoomable: false });
    });
  }

  function findInd(name) {
    if (!payload) return null;
    return (payload.industries || []).find((i) => i.name === name) || null;
  }
  function setUrlInd(name) {
    try {
      const u = new URL(window.location.href);
      if (name) u.searchParams.set("ind", name); else u.searchParams.delete("ind");
      history.replaceState(null, "", u.pathname + u.search + u.hash);
    } catch (e) {}
  }
  function openIndustry(name) {
    const ind = findInd(name);
    if (!ind) return;
    hideTip();
    activeInd = name;
    setUrlInd(name);
    renderL1(ind);
    window.scrollTo(0, 0);
  }
  function backToL0() {
    activeInd = null;
    setUrlInd(null);
    l1El.hidden = true;
    l0El.hidden = false;
    hideTip();
    if (payload) render(payload);
  }
  backEl.addEventListener("click", backToL0);
  listBtn.addEventListener("click", () => {
    listMode = !listMode;
    if (cachedIndustries.length) renderNarrowBands(cachedIndustries);
  });

  function pickAreaMode(data) {
    let q = "";
    try { q = new URLSearchParams(window.location.search).get("area") || ""; } catch (e) {}
    const hasFloat = (data.industries || []).some((i) => (i.stocks || []).some((s) => Number(s.float_mktcap) > 0));
    if (q === "sqrt" || q === "total") return q;
    if (q === "float") return hasFloat ? "float" : "sqrt";
    const d = data.area_default;
    if (d === "float") return hasFloat ? "float" : "sqrt";
    if (d === "sqrt" || d === "total") return d;
    return hasFloat ? "float" : "sqrt";
  }

  function render(data) {
    const industries = (data.industries || []).filter((ind) => Array.isArray(ind.stocks) && ind.stocks.length);
    cachedIndustries = industries;
    if (!industries.length) {
      metaEl.textContent = UI.empty;
      mapEl.hidden = false;
      mapEl.classList.remove("map-flow");
      mapEl.innerHTML = '<div class="empty">' + escapeHtml(UI.empty) + "</div>";
      listEl.hidden = true; listEl.innerHTML = ""; listBtn.hidden = true;
      return;
    }
    areaMode = pickAreaMode(data);
    const stocksN = data.stock_count || industries.reduce((s, i) => s + i.stocks.length, 0);
    const g = String(data.generated_at || "");
    const time = g.length >= 16 ? g.slice(5, 10) + " " + g.slice(11, 16) : "—";
    const tpl = areaMode === "sqrt" ? COPY.meta_sqrt : areaMode === "total" ? COPY.meta_total : COPY.meta;
    metaEl.textContent = fill(tpl, { date: data.asof || "—", time: time, n: stocksN });
    const noteSqrt = document.getElementById("hm-note-sqrt");
    if (noteSqrt) noteSqrt.hidden = areaMode !== "sqrt";
    let want = activeInd;
    try { const q = new URLSearchParams(window.location.search).get("ind"); if (q) want = q; } catch (e) {}
    if (want && findInd(want)) { openIndustry(want); return; }
    l1El.hidden = true;
    l0El.hidden = false;
    if (isNarrow()) renderNarrowBands(industries);
    else { listMode = false; activeInd = null; renderDesktop(industries); }
  }

  function redraw() { if (payload) render(payload); }

  fetch("/api/heatmap.json", { headers: { Accept: "application/json" } })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then((data) => { payload = data; render(data); })
    .catch((err) => {
      metaEl.textContent = UI.loadFailed;
      mapEl.hidden = false;
      mapEl.innerHTML = '<div class="empty">' + escapeHtml(UI.loadFailed) + "（" +
        escapeHtml(String((err && err.message) || err)) + "）</div>";
    });

  let lastW = window.innerWidth;
  window.addEventListener("resize", (() => {
    let t = 0;
    return () => {
      if (Math.abs(window.innerWidth - lastW) < 2 && isNarrow()) return; // ignore mobile URL-bar height jitter
      lastW = window.innerWidth;
      clearTimeout(t); t = setTimeout(redraw, 140);
    };
  })());
  window.addEventListener("popstate", redraw);
})();
</script>`;
}
