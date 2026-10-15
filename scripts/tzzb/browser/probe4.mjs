import { chromium } from "playwright-core";
const b = await chromium.launch({ channel: "msedge", headless: true });
const ctx = await b.newContext();
const p = await ctx.newPage();
await p.goto("https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=CM3ntt2&user_key=187735", { waitUntil: "networkidle", timeout: 45000 });
await p.waitForTimeout(2000);
const v = (await ctx.cookies()).find((c) => c.name === "v")?.value;
const ua = await p.evaluate(() => navigator.userAgent);
// 同一浏览器上下文(同 cookie/指纹)用 APIRequestContext 发, 等价于页面发出的请求
for (const [k, u] of [["CM3ntt2", "187735"], ["joonDP3", "168384"]]) {
    const r = await ctx.request.get(`https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/profit_rate_by_share?key=${k}&user_key=${u}&hexin-v=${v}`,
        { headers: { Referer: "https://tzzb.10jqka.com.cn/", "hexin-v": v } });
    const t = await r.text();
    let info = t.slice(0, 100);
    try { const j = JSON.parse(t); const L = j?.ex_data?.index_list || []; info = `err=${j.error_code} 条数 ${L.length} 最新 ${L.reduce((m, x) => (x.date > m ? x.date : m), "")}`; } catch { /* html */ }
    console.log(k, u, r.status(), info);
}
console.log("UA", ua.slice(0, 80), "v", v?.slice(0, 16));
await b.close();
