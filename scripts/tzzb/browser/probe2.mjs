import { chromium } from "playwright-core";
const [key, uk] = [process.argv[2] || "CM3ntt2", process.argv[3] || "187735"];
const b = await chromium.launch({ channel: "msedge", headless: true });
const p = await b.newPage();
const seen = [];
p.on("response", async (r) => {
    const t = r.request().resourceType();
    if (t === "xhr" || t === "fetch") seen.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 200)}`);
});
await p.goto(`https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=${key}&user_key=${uk}`, { waitUntil: "networkidle", timeout: 45000 });
await p.waitForTimeout(3000);
console.log(seen.join("\n"));
await b.close();
