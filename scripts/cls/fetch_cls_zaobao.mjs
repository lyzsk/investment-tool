// fetch_cls_zaobao.mjs — 财联社早报(文章通道)抓取 + md 挂载(盘前新闻事实层, 2026-10-02)
// 背景: 早报是"文章"不是"电报", 不在 www.cls.cn/api/cache?name=telegraph 端点(实测 20 条 0 早报),
//       发在 api3.cls.cn/share/article/<id>, 公开无鉴权; Java 爬虫看不到它=端点问题非失败
// 用法(同 fetch_wechat.mjs 模式, 发现层=人工贴链接, hermes 语法 "早报+链接"):
//   node scripts/cls/fetch_cls_zaobao.mjs --url <api3.cls.cn/share/article/...> [--date yyyy-MM-dd] [--write] [--force]
//   node scripts/cls/fetch_cls_zaobao.mjs --remount --date <d> [--write]   # spec.md 更新后重挂
//   node scripts/cls/fetch_cls_zaobao.mjs --discover [--date d] [--write]  # 10/14 自动发现: 不用贴链接, 从早报专题页找当日【早报】
//     发现源= api3.cls.cn/share/subject/1151(财联社 App 分享用的 H5 专题页, 公开无签名无鉴权; 1151=早报专题, 文章页 subjectid=1151 实证)
//     取页内第一条【早报】→ 抓文章 → 校验文章日期=目标日(默认今天), 不符=当日早报尚未发布(出口 6, 不落产物)
//     共 2 个请求/天; 失败照旧可人工贴链接(--url 路保留)
// 产物: downloads/cls_zaobao/<yyyy-MM-dd>/{raw.html,text.md,meta.json,spec.md}
//   spec.md = hermes 蒸馏要点(五栏: 宏观/行业/公司/环球/机会, 每行一条 【早报要点】<栏>: <内容>)
// 挂载: md/<y>S<q>/<date>.md 的 ## 盘前 → ### 财联社早报(整小节覆盖幂等, spec 不存在时保旧【早报要点】行)
//   原文不进 md(同发哥线口径: 原文住证据层, md 只放加工产物)
// 出口: 0=ok 1=抓取失败 3=解析失败 4=无md 5=反爬 6=--discover 未找到目标日早报(未发布/专题页改版)
// 防封铁律: 伪装桌面 Chrome + 3 次退避重试 + 抖动 ×0.75~1.25; 失败显式非0, 不编数据
import fs from "node:fs";
import path from "node:path";
import { gfetch } from "../lib/req_guard.mjs";   // 10/15 统一请求层: 按域名记账/熔断/日预算(scripts/lib/req_guard_sources.json)

const ARGS = process.argv.slice(2);
const opt = (k) => { const i = ARGS.indexOf(k); return i === -1 ? null : ARGS[i + 1]; };
let URL_IN = opt("--url");
const DISCOVER = process.argv.includes("--discover");
const DATE_IN = opt("--date");
const WRITE = ARGS.includes("--write");
const FORCE = ARGS.includes("--force");
const REMOUNT = ARGS.includes("--remount");
if (!URL_IN && !REMOUNT && !DISCOVER) {
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
    // 10/13 修: 页面时间改为 data-time="<unix 秒>"(原 "yyyy-MM-dd HH:mm:ss" 文本匹配不到 → ctime=null → 正文推算误取
    // 新闻里的"2027年4月1日起…"算成 2027-04-02); 先认文本时间, 再认 data-time(按北京时间格式化)
    let ctime = (html.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/) || [])[1] || null;
    const dt = html.match(/data-time="(\d{10})"/);
    if (!ctime && dt) ctime = new Date(+dt[1] * 1000).toLocaleString("sv-SE", { timeZone: "Asia/Shanghai" });
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
        const today = new Date().toLocaleString("sv-SE", { timeZone: "Asia/Shanghai" }).slice(0, 10);
        if (DISCOVER) {   // 10/14: 早报专题页找最新一条【早报】(页面按时间倒序)
            let sub = null, e1 = "";
            for (let i = 1; i <= 3 && !sub; i++) {
                try {
                    const r = await gfetch("https://api3.cls.cn/share/subject/1151?os=android&sv=884", { headers: UA });
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    sub = await r.text();
                } catch (e) { e1 = e.message; if (i < 3) await sleep(jitter(1000 * i)); }
            }
            if (!sub) { console.error(`专题页抓取失败: ${e1}`); process.exit(1); }
            const m = sub.match(/share\/article\/(\d+)[^"]*">\s*<span[^>]*>\s*(【早报】[^<]*)</);
            if (!m) { console.error("专题页未找到【早报】条目(改版?), 请人工贴链接走 --url"); process.exitCode = 6; return; }  // exitCode+return: Windows 下有未关连接时 process.exit 会触发 libuv 断言(10/11 collect_daily 同坑)
            URL_IN = `https://api3.cls.cn/share/article/${m[1]}?os=android&sv=884&app=cailianpress`;
            console.log(`发现: ${m[2].slice(0, 40)} → ${URL_IN}`);
            await sleep(jitter(1200));
        }
        let html = null, lastErr = "";
        for (let i = 1; i <= 3; i++) {
            try {
                const r = await gfetch(URL_IN, { headers: UA, redirect: "follow" });
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
        // 10/15 修: --discover 时日期必须取页面 ctime 再和 --date 比对; 原先 --date 直接覆盖 → 下面的"不是目标日"检查永远通过,
        // 07:00:27 专题页最新一条还是 10/14 早报, 被当成 10/15 落盘+蒸馏(01 发现要点与昨日逐条重合)
        if (DATE_IN && !DISCOVER) { date = DATE_IN; }
        else if (p.ctime) { date = p.ctime.slice(0, 10); }
        else {
            const m = p.text.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
            const d = m ? new Date(+m[1], +m[2] - 1, +m[3] + 1) : null;  // 早报=昨日新闻+1
            if (d && Math.abs(d - Date.now()) <= 3 * 86400000) {   // 10/13: 离今天 >3 天=多半是新闻里的政策生效日等, 不可信
                date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                console.log(`ctime 空, 从正文"${m[0]}"推算发布日 → ${date}`);
            } else {
                console.error(`❌ 无法确定早报日期: ctime 空 + 正文日期线索${m ? `"${m[0]}"离今天超过 3 天(疑为新闻内容日期)` : "缺失"}; 请用 --date yyyy-MM-dd 指定`);
                process.exit(4);
            }
        }
        if (DISCOVER && date !== (DATE_IN || today)) {   // 专题页最新一条不是目标日=当日早报还没发(07:00 发)
            console.error(`最新早报日期 ${date} ≠ 目标日 ${DATE_IN || today}: 当日早报尚未发布(或 --date 指定的不是最新一期), 不落产物`);
            process.exitCode = 6; return;
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
