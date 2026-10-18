// 自己起 Edge(不带自动化标记, navigator.webdriver=false), playwright 只通过 CDP 旁听网络
import { chromium } from "playwright-core";
import { spawn } from "child_process";
import fs from "fs";
const E = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"].find((p) => fs.existsSync(p));
const prof = process.env.TEMP + "/tzzb_edge_prof";
const ed = spawn(E, ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${prof}`, "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore", windowsHide: true });
await new Promise((r) => setTimeout(r, 2500));
const b = await chromium.connectOverCDP("http://127.0.0.1:9333");
const ctx = b.contexts()[0];
const p = await ctx.newPage();
const seen = [];
p.on("response", async (r) => {
    if (/caishen_fund|caishen_httpserver/.test(r.url()) && !/getTime/.test(r.url())) {
        let body = ""; try { body = (await r.text()).slice(0, 90); } catch { /* */ }
        seen.push(`${r.status()} ${r.url().replace(/hexin-v=[^&]+/, "hexin-v=…").slice(0, 160)} ${body}`);
    }
});
console.log("webdriver:", await p.evaluate(() => navigator.webdriver));
await p.goto(`https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=${process.argv[2] || "CM3ntt2"}&user_key=${process.argv[3] || "187735"}`, { waitUntil: "networkidle", timeout: 45000 });
await p.waitForTimeout(8000);
console.log(seen.join("\n") || "(无数据请求)");
await b.close(); ed.kill();
