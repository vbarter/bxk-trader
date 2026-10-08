import { getPlatformProxy } from "wrangler";
import fs from "fs";
import path from "path";

const DATA = "/root/dev/Sequoia-X/data";
const { env, dispose } = await getPlatformProxy({
  configPath: "./wrangler.jsonc",
  persist: { path: ".wrangler/state" },
});

const bucket = env.PICKS;
const ct = "application/json; charset=utf-8";

async function put(key, file) {
  const body = fs.readFileSync(file);
  await bucket.put(key, body, { httpMetadata: { contentType: ct } });
}

console.log("Putting top-level...");
await put("latest.json", path.join(DATA, "latest.json"));
await put("watch_calendar.json", path.join(DATA, "watch_calendar.json"));
await put("news_events.json", path.join(DATA, "news_events.json"));
await put("heatmap.json", path.join(DATA, "heatmap.json"));
console.log("Top-level done");

const detailsDir = path.join(DATA, "details");
const files = fs.readdirSync(detailsDir).filter((f) => f.endsWith(".json"));
console.log(`Putting ${files.length} details...`);
let n = 0;
const concurrency = 48;
for (let i = 0; i < files.length; i += concurrency) {
  const chunk = files.slice(i, i + concurrency);
  await Promise.all(chunk.map((f) => put(`details/${f}`, path.join(detailsDir, f))));
  n += chunk.length;
  if (n % 96 === 0 || n === files.length) console.log(`  ${n}/${files.length}`);
}

console.log("Verify:", {
  latest: !!(await bucket.get("latest.json")),
  calendar: !!(await bucket.get("watch_calendar.json")),
  news: !!(await bucket.get("news_events.json")),
  heatmap: !!(await bucket.get("heatmap.json")),
  sample: !!(await bucket.get(`details/${files[0]}`)),
});
await dispose();
console.log("DONE");
