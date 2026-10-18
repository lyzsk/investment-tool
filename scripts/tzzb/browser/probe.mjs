// 探针: 真实 Edge 打开账本页(让同花顺反爬脚本 chameleon 生效), 再在页面上下文里 fetch API, 看能否 200
import { chromium } from "playwright-core";
const [key, uk] = [process.argv[2] || "CM3ntt2", process.argv[3] || "187735"];
const b = await chromium.launch({ channel: "msedge", headless: true });
const p = await b.newPage();
const seen = [];
p.on("response", (r) => { if (/caishen_fund/.test(r.url())) seen.push(`${r.status()} ${r.url().split("?")[0].split("/").slice(-2).join("/")}`); });
await p.goto(`https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=${key}&user_key=${uk}`, { waitUntil: "networkidle", timeout: 45000 });
console.log("页面自身请求:", seen.slice(0, 12));
const r = await p.evaluate(async ([k, u]) => {
    const out = {};
    for (const ep of ["profit_rate_by_share", "position_change_by_share"]) {
        const res = await fetch(`//tzzb.10jqka.com.cn/caishen_httpserver/tzzb/caishen_fund/community_share/v1/${ep}?key=${k}&user_key=${u}${ep.startsWith("position_change") ? "&page=1" : ""}`, { credentials: "include" });
        const t = await res.text();
        out[ep] = `${res.status} ${t.slice(0, 120)}`;
    }
    return out;
}, [key, uk]);
console.log(r);
await b.close();
