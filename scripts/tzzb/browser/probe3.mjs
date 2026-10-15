import { chromium } from "playwright-core";
const [key, uk] = [process.argv[2] || "CM3ntt2", process.argv[3] || "187735"];
const b = await chromium.launch({ channel: "msedge", headless: true });
const ctx = await b.newContext();
const p = await ctx.newPage();
const seen = [];
p.on("response", (r) => { if (/hexin|10jqka/.test(r.url()) && !/\.(js|css|png|jpg|svg|woff2?)(\?|$)/.test(r.url())) seen.push(`${r.status()} ${r.request().resourceType()} ${r.url().slice(0, 170)}`); });
await p.goto(`https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=${key}&user_key=${uk}`, { waitUntil: "networkidle", timeout: 45000 });
await p.waitForTimeout(15000); await p.mouse.wheel(0, 2000); await p.waitForTimeout(5000);
console.log(seen.join("\n"));
const ck = await ctx.cookies();
console.log("cookies:", ck.map((c) => `${c.domain}:${c.name}=${String(c.value).slice(0, 20)}`).join(" | "));
const r0 = 0; const r = "skip"; if (0) await p.evaluate(async ([k, u]) => {
    const v = (document.cookie.match(/(?:^|; )v=([^;]+)/) || [])[1] || "";
    const res = await fetch(`https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/profit_rate_by_share?key=${k}&user_key=${u}&hexin-v=${v}`);
    return `v=${v.slice(0, 12)}… ${res.status} ${(await res.text()).slice(0, 160)}`;
}, [key, uk]);
console.log("带 cookie v 作 hexin-v:", r);
await b.close();
