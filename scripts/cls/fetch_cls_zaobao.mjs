// fetch_cls_zaobao.mjs — 财联社早报(文章通道)抓取 + md 挂载(盘前新闻事实层, 2026-10-02)
// 背景: 早报是"文章"不是"电报", 不在 www.cls.cn/api/cache?name=telegraph 端点(实测 20 条 0 早报),
//       发在 api3.cls.cn/share/article/<id>, 公开无鉴权; Java 爬虫看不到它=端点问题非失败
// 用法(同 fetch_wechat.mjs 模式, 发现层=人工贴链接, hermes 语法 "早报+链接"):
//   node scripts/cls/fetch_cls_zaobao.mjs --url <api3.cls.cn/share/article/...> [--date yyyy-MM-dd] [--write] [--force]
//   node scripts/cls/fetch_cls_zaobao.mjs --remount --date <d> [--write]   # spec.md 更新后重挂
// 产物: downloads/cls_zaobao/<yyyy-MM-dd>/{raw.html,text.md,meta.json,spec.md}
//   spec.md = hermes 蒸馏要点(五栏: 宏观/行业/公司/环球/机会, 每行一条 【早报要点】<栏>: <内容>)
// 挂载: md/<y>S<q>/<date>.md 的 ## 盘前 → ### 财联社早报(整小节覆盖幂等, spec 不存在时保旧【早报要点】行)
//   原文不进 md(同发哥线口径: 原文住证据层, md 只放加工产物)
// 出口: 0=ok 1=抓取失败 3=解析失败 4=无md 5=反爬
// 防封铁律: 伪装桌面 Chrome + 3 次退避重试 + 抖动 ×0.75~1.25; 失败显式非0, 不编数据
import fs from "node:fs";
import path from "node:path";

const ARGS = process.argv.slice(2);
const opt = (k) => { const i = ARGS.indexOf(k); return i === -1 ? null : ARGS[i + 1]; };
const URL_IN = opt("--url");
const DATE_IN = opt("--date");
const WRITE = ARGS.includes("--write");
const FORCE = ARGS.includes("--force");
const REMOUNT = ARGS.includes("--remount");
if (!URL_IN && !REMOUNT) {
    console.error("用法: node scripts/cls/fetch_cls_zaobao.mjs --url <url> [--date d] [--write] [--force]\n      node scripts/cls/fetch_cls_zaobao.mjs --remount --date <d> [--write]");
    process.exit(1);
}

const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept-Language": "zh-CN,zh;q=0.9" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (base) => base * (0.75 + Math.random() * 0.5);

function decode(s) {
    return s.replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&#39;|&apos;/g, "'")
        .replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&hellip;/g, "…");
}

function parse(html) {
    if (/环境异常|完成验证后即可继续访问|操作频繁/.test(html)) return { err: 5, msg: "反爬验证页" };
    const title = decode((html.match(/<title>([^<]*)<\/title>/) || [])[1] || "").trim();
    const body = html.match(/<div class="content">([\s\S]*?)<\/div>\s*<\/section>/);
    if (!title || !body) return { err: 3, msg: `解析失败(title=${!!title} body=${!!body})` };
    const text = decode(body[1].replace(/<br[^>]*>/gi, "\n").replace(/<\/(p|section|h[1-6]|li)>/gi, "\n")
        .replace(/<[^>]+>/g, "")).replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (text.length < 100) return { err: 3, msg: `正文过短(${text.length}字), 疑解析错位` };
    const ctime = (html.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/) || [])[1] || null;
    return { title, ctime, text };
}

function mount(date, meta) {
    const [y, m] = date.split("-");
    const md = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${date}.md`);
    if (!fs.existsSync(md)) return { code: 4, msg: "无md" };
    const lines = fs.readFileSync(md, "utf8").split("\n");
    // 找/补骨架: ## 盘前 → ### 财联社早报
    let pi = lines.findIndex((l) => /^## /.test(l) && l.replace(/\s/g, "") === "##盘前");
    if (pi === -1) {
        const at = /^# /.test(lines[0] || "") ? 1 : 0;
        lines.splice(at, 0, "", "## 盘前", "");
        pi = at + 1;
    }
    let pEnd = lines.length;
    for (let i = pi + 1; i < lines.length; i++) if (/^## /.test(lines[i])) { pEnd = i; break; }
    let hi = -1;
    for (let i = pi + 1; i < pEnd; i++) if (/^### /.test(lines[i]) && lines[i].replace(/\s/g, "") === "###财联社早报") { hi = i; break; }
    const created = hi === -1;
    if (created) { lines.splice(pEnd, 0, `### 财联社早报`, ""); hi = pEnd; }
    let hEnd = lines.length;
    for (let i = hi + 1; i < lines.length; i++) if (/^#{2,3} /.test(lines[i])) { hEnd = i; break; }
    const old = lines.slice(hi + 1, hEnd);
    const specFile = path.join("downloads", "cls_zaobao", date, "spec.md");
    let specLines = null;
    if (fs.existsSync(specFile)) specLines = fs.readFileSync(specFile, "utf8").split("\n").map((l) => l.trimEnd()).filter((l) => l.trim());
    if (!specLines) specLines = old.filter((l) => l.includes("【早报要点】"));
    const block = [`### 财联社早报`, "", `> ${meta.title} · ${meta.ctime || date} · [原文链接](${meta.url})`, ""];
    if (specLines.length) block.push(...specLines, "");
    if (block[block.length - 1] !== "") block.push("");
    lines.splice(hi, hEnd - hi, ...block);
    fs.writeFileSync(md, lines.join("\n"));
    return { code: 0, msg: `${created ? "新建小节" : "覆盖"}(保${specLines.length}要点)` };
}

(async () => {
    let date, meta;
    if (REMOUNT) {
        date = DATE_IN;
        const dir = path.join("downloads", "cls_zaobao", date);
        meta = JSON.parse(fs.readFileSync(path.join(dir, "meta.json"), "utf8"));
    } else {
        let html = null, lastErr = "";
        for (let i = 1; i <= 3; i++) {
            try {
                const r = await fetch(URL_IN, { headers: UA, redirect: "follow" });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                html = await r.text();
                break;
            } catch (e) { lastErr = e.message; if (i < 3) await sleep(jitter(1000 * i)); }
        }
        if (!html) { console.error(`抓取失败: ${lastErr}`); process.exit(1); }
        const p = parse(html);
        if (p.err) { console.error(p.msg); process.exit(p.err); }
        if (!p.title.includes("早报")) console.warn(`⚠️ 标题不含"早报": ${p.title}`);
        // 10/7 修: ctime 提取失败(null)时不再回退到今天——早报讲的是昨天新闻, 回退今天必错;
        // 改为从正文首段提取"X月X日"推算发布日(+1), 提不出则报错要求 --date
        if (DATE_IN) { date = DATE_IN; }
        else if (p.ctime) { date = p.ctime.slice(0, 10); }
        else {
            const m = p.text.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
            if (m) {
                const d = new Date(+m[1], +m[2] - 1, +m[3] + 1);  // 早报=昨日新闻+1
                date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                console.log(`ctime 空, 从正文"${m[0]}"推算发布日 → ${date}`);
            } else {
                console.error("❌ 无法确定早报日期: ctime 空 + 正文无日期线索; 请用 --date yyyy-MM-dd 指定");
                process.exit(4);
            }
        }
        meta = { title: p.title, ctime: p.ctime, url: URL_IN, fetchedAt: new Date().toISOString(), chars: p.text.length };
        const dir = path.join("downloads", "cls_zaobao", date);
        fs.mkdirSync(dir, { recursive: true });
        if (!FORCE && fs.existsSync(path.join(dir, "meta.json"))) console.log("产物已存在, 覆盖(要保留旧件先备份)");
        fs.writeFileSync(path.join(dir, "raw.html"), html);
        fs.writeFileSync(path.join(dir, "text.md"), p.text);
        fs.writeFileSync(path.join(dir, "meta.json"), JSON.stringify(meta, null, 2));
        console.log(`已抓: ${p.title} | ${p.ctime} | ${p.text.length}字 → ${dir}/`);
    }
    if (WRITE) {
        const r = mount(date, meta);
        if (r.code) { console.error(`挂载失败: ${r.msg}`); process.exit(r.code); }
        console.log(`已挂载 md ${date}: ${r.msg}`);
    } else {
        console.log("(--write 才挂 md; 蒸馏后把【早报要点】写进产物目录 spec.md, 再 --remount --write)");
    }
    console.log(`JSON:${JSON.stringify({ date, title: meta.title })}`);
})();
