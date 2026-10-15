// browser_transport.mjs — 同花顺投资账本接口的浏览器代发通道(10/15 凌晨建)
// 背景: 10/14 15:13 起 community_share/v1/* 必须带页面反爬脚本(chameleon.js)实时生成的 hexin-v, 否则 Nginx 403(换 IP、
//   真浏览器直连 URL 都 403; 静态/过期 hexin-v 也 403)。自动化框架启动的浏览器(navigator.webdriver=true)页面不发数据请求。
// 做法(不伪造令牌): 自己起一个普通无头 Edge(不带自动化标记, 零弹窗), 打开一个账本分享页让 chameleon 正常加载,
//   之后所有接口请求都在该页面上下文里用 XMLHttpRequest 发——和页面自己的请求走同一条路, 令牌由页面脚本生成。
// 用法: import { BrowserTransport } from "./browser/browser_transport.mjs";
//       const t = await BrowserTransport.open({ key, user_key });  const { status, text } = await t.get(url);  await t.close();
import { chromium } from "playwright-core";
import { spawn } from "child_process";
import fs from "fs";
import path from "path";

const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"]
    .find((p) => fs.existsSync(p));
const PORT = 9333 + Math.floor(Math.random() * 300);

export class BrowserTransport {
    static async open({ key, user_key }) {
        if (!EDGE) throw new Error("找不到 Edge");
        const prof = path.join(process.env.TEMP || "/tmp", "tzzb_edge_prof");
        const ed = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, "--no-first-run",
            "--disable-gpu", "--disable-extensions", "about:blank"], { stdio: "ignore", windowsHide: true });
        let b;
        for (let i = 0; i < 20 && !b; i++) {
            await new Promise((r) => setTimeout(r, 500));
            try { b = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`); } catch { /* 还没起来 */ }
        }
        if (!b) { ed.kill(); throw new Error("Edge CDP 连接失败"); }
        const t = new BrowserTransport(); t.ed = ed; t.b = b;
        t.page = await b.contexts()[0].newPage();
        await t.page.goto(`https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=${key}&user_key=${user_key}`,
            { waitUntil: "networkidle", timeout: 60000 });
        await t.page.waitForTimeout(2500);
        process.on("exit", () => { try { ed.kill(); } catch { /* ignore */ } });
        return t;
    }

    // 页面上下文 XHR(chameleon 钩住 XHR 自动补 hexin-v); 不带凭证(跨域只放行无凭证请求)
    async get(url) {
        const u = url.includes("terminal=") ? url : url + (url.includes("?") ? "&" : "?") + "terminal=1&version=2";
        return await this.page.evaluate((x) => new Promise((res) => {
            const r = new XMLHttpRequest();
            r.open("GET", x);
            r.timeout = 30000;
            r.onload = () => res({ status: r.status, text: r.responseText });
            r.onerror = () => res({ status: 0, text: "XHR error" });
            r.ontimeout = () => res({ status: 0, text: "XHR timeout" });
            r.send();
        }), u);
    }

    async close() {
        try { await this.b.close(); } catch { /* ignore */ }
        try { this.ed.kill(); } catch { /* ignore */ }
    }
}
