// 验证: 页面上下文里用 XMLHttpRequest 发同样的接口(chameleon 会像对页面自己的请求一样自动补 hexin-v)
import { chromium } from "playwright-core";
import { spawn } from "child_process";
import fs from "fs";
const E = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"].find((p) => fs.existsSync(p));
const ed = spawn(E, ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${process.env.TEMP}/tzzb_edge_prof`, "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore", windowsHide: true });
await new Promise((r) => setTimeout(r, 2500));
const b = await chromium.connectOverCDP("http://127.0.0.1:9333");
const p = await b.contexts()[0].newPage();
const [key, uk] = ["CM3ntt2", "187735"];
await p.goto(`https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=${key}&user_key=${uk}`, { waitUntil: "networkidle", timeout: 45000 });
await p.waitForTimeout(3000);
const r = await p.evaluate(async ([k, u]) => {
    const B = "https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/";
    const get = (url) => new Promise((res) => { const x = new XMLHttpRequest(); x.open("GET", url);
        x.onload = () => res(`${x.status} ${x.responseText.slice(0, 110)}`); x.onerror = () => res("ERR"); x.send(); });
    return {
        pc2: await get(`${B}position_change_by_share?terminal=1&version=2&page=2&count=50&key=${k}&user_key=${u}`),
        bs: await get(`${B}change_bs_by_share?terminal=1&version=2&key=${k}&user_key=${u}&stock_code=301716&page=1`),
        old: await get(`${B}profit_rate_by_share?terminal=1&version=2&key=joonDP3&user_key=168384`),
    };
}, [key, uk]);
console.log(r);
await b.close(); ed.kill();
