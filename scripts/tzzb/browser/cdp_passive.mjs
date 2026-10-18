// cdp_passive.mjs — tzzb 防反爬 B/C 层(10/15 建, TODO A11)
// B=纯被动监听: 自己起普通无头 Edge(零弹窗, 用户目录固定复用), 用**原生 CDP**(WebSocket, 不经 playwright, 不在页面执行任何 JS)
//   只开 Network 域, 打开账本页/个股页让页面自己发请求, Network.responseReceived+loadingFinished 后 Network.getResponseBody 取原始 JSON。
// C=读渲染后页面文字: 同一页面加载完后用 DOM.getDocument+DOM.getOuterHTML(仍不执行 JS)拿渲染后的 HTML, 转纯文本交给解析器。
// 导出: openEdge() / capturePage(edge, url, {match, settleMs, maxMs}) → {responses:[{url,status,body}], html, text}
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"]
    .find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const PROFILE = path.join(process.env.TEMP || "/tmp", "tzzb_edge_prof");   // 与 A 层同一个目录(像老用户, cookie/缓存复用); 同一时刻只能一个 Edge 用它

export async function openEdge() {
    if (!EDGE) throw new Error("找不到 Edge");
    const port = 9640 + Math.floor(Math.random() * 300);
    const ed = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${PROFILE}`, "--no-first-run",
        "--disable-gpu", "--disable-extensions", "about:blank"], { stdio: "ignore", windowsHide: true });
    process.on("exit", () => { try { ed.kill(); } catch { /* */ } });
    for (let i = 0; i < 30; i++) {
        await sleep(400);
        try { const r = await fetch(`http://127.0.0.1:${port}/json/version`); if (r.ok) return { ed, port, close: () => { try { ed.kill(); } catch { /* */ } } }; } catch { /* 未起 */ }
    }
    try { ed.kill(); } catch { /* */ }
    throw new Error("Edge CDP 端口未就绪(用户目录被另一个 Edge 占用?)");
}

class Cdp {
    constructor(ws) {
        this.ws = ws; this.id = 0; this.wait = new Map(); this.handlers = [];
        ws.addEventListener("message", (ev) => {
            const m = JSON.parse(typeof ev.data === "string" ? ev.data : Buffer.from(ev.data).toString());
            if (m.id && this.wait.has(m.id)) { const { res, rej } = this.wait.get(m.id); this.wait.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
            else if (m.method) for (const h of this.handlers) h(m.method, m.params);
        });
    }
    static async connect(url) {
        const ws = new WebSocket(url);
        await new Promise((res, rej) => { ws.addEventListener("open", res, { once: true }); ws.addEventListener("error", () => rej(new Error("CDP WebSocket 连接失败")), { once: true }); });
        return new Cdp(ws);
    }
    send(method, params = {}) {
        const id = ++this.id;
        this.ws.send(JSON.stringify({ id, method, params }));
        return new Promise((res, rej) => { this.wait.set(id, { res, rej }); setTimeout(() => { if (this.wait.delete(id)) rej(new Error(`CDP ${method} 超时`)); }, 30000); });
    }
    on(fn) { this.handlers.push(fn); }
    close() { try { this.ws.close(); } catch { /* */ } }
}

// HTML → 纯文本(去 script/style, 块级标签换行); 只为 C 层解析用
export function htmlToText(html) {
    return html.replace(/<(script|style|noscript)[\s\S]*?<\/\1>/gi, "")
        .replace(/<(br|\/p|\/div|\/li|\/tr|\/h\d|\/section|\/ul|\/table)[^>]*>/gi, "\n")
        .replace(/<\/t[dh]>/gi, "\t").replace(/<[^>]+>/g, "")
        .replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n))
        .split("\n").map((l) => l.replace(/[ \t]+/g, " ").trim()).filter(Boolean).join("\n");
}

// 打开一个页面(新 target), 被动记录匹配 match 的响应体; 网络静默 settleMs 或到 maxMs 收尾; 之后取渲染后 HTML
export async function capturePage(edge, url, { match = /community_share/, settleMs = 4000, maxMs = 45000, wantHtml = true } = {}) {
    const t = await (await fetch(`http://127.0.0.1:${edge.port}/json/new?about:blank`, { method: "PUT" })).json();
    const cdp = await Cdp.connect(t.webSocketDebuggerUrl);
    const reqs = new Map(), done = [], pending = new Set();
    let last = Date.now();
    cdp.on((m, p) => {
        if (m === "Network.responseReceived" && match.test(p.response.url)) { reqs.set(p.requestId, { url: p.response.url, status: p.response.status }); pending.add(p.requestId); last = Date.now(); }
        else if (m === "Network.loadingFinished" && reqs.has(p.requestId)) {
            const r = reqs.get(p.requestId);
            cdp.send("Network.getResponseBody", { requestId: p.requestId })
                .then((b) => done.push({ ...r, body: b.base64Encoded ? Buffer.from(b.body, "base64").toString("utf8") : b.body }))
                .catch((e) => done.push({ ...r, body: null, err: e.message }))
                .finally(() => { pending.delete(p.requestId); last = Date.now(); });
        } else if (m === "Network.loadingFailed" && reqs.has(p.requestId)) { done.push({ ...reqs.get(p.requestId), body: null, err: p.errorText }); pending.delete(p.requestId); }
        else if (m && m.startsWith("Network.")) last = Date.now();
    });
    await cdp.send("Network.enable", { maxResourceBufferSize: 20e6, maxTotalBufferSize: 60e6 });
    await cdp.send("Page.enable");
    const t0 = Date.now();
    await cdp.send("Page.navigate", { url });
    await sleep(1500);
    while (Date.now() - t0 < maxMs && (pending.size || Date.now() - last < settleMs)) await sleep(300);
    let html = "";
    if (wantHtml) {
        try {
            const doc = await cdp.send("DOM.getDocument", { depth: -1 });
            html = (await cdp.send("DOM.getOuterHTML", { nodeId: doc.root.nodeId })).outerHTML;
        } catch { /* C 层拿不到就空 */ }
    }
    cdp.close();
    try { await fetch(`http://127.0.0.1:${edge.port}/json/close/${t.id}`); } catch { /* */ }
    return { responses: done, html, text: html ? htmlToText(html) : "" };
}

// CLI 探针: node scripts/tzzb/browser/cdp_passive.mjs <url>   → 列出页面自己请求的接口+状态+体长, 文本前 1500 字
if (process.argv[1] && path.resolve(process.argv[1]).endsWith("cdp_passive.mjs") && process.argv[2]) {
    const edge = await openEdge();
    try {
        const r = await capturePage(edge, process.argv[2], { match: /hexin\.cn|10jqka\.com\.cn\/.*\.(json|do)|caishen/ });
        for (const x of r.responses) console.log(x.status, x.url.slice(0, 160), x.body ? x.body.length : x.err);
        console.log("---- text ----\n" + r.text.slice(0, +(process.argv[3] || 1500)));
        if (process.argv[4]) fs.writeFileSync(process.argv[4], JSON.stringify(r, null, 1));
    } finally { edge.close(); }
}
