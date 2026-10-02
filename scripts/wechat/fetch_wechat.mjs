// fetch_wechat.mjs — 微信公众号文章抓取 + md 挂载(盘前语料线, 2026-10-02)
// 入口: hermes(盘前贴链接即跑) / Claude 晚间兜底; Java cron 不参与(发现层人工化, 用户拍板)
// 用法:
//   node scripts/wechat/fetch_wechat.mjs --url <mp.weixin.qq.com/s/...> [--date yyyy-MM-dd] [--write] [--force]
//   --date 不传=用页面 createTime; --write=挂载进 md; --force=产物已存在也重抓
// 产物(证据层, 当天必抓——作者会删文, 9/29 实测"昨天的文章被GG了"):
//   downloads/wechat/<account>/<yyyy-MM-dd>/raw.html + text.md(正文纯文本) + meta.json
//   可选 spec.md = fage-skill 盘前蒸馏产出(【推演要点】), --write 时插到 meta 行下
// 挂载: md/<y>S<q>/<date>.md 的 ## 盘前 → ### 微信公众号 → #### <name> 小节
//   整小节覆盖幂等; 保旧【核销】行; spec.md 不存在时保旧【推演要点】行; 骨架缺失自动补(补在文首)
//   原文不进 md(10/2 用户裁决: 与桃哥/tzzb 同口径——原文住证据层, md 只放加工产物)
// 出口: 0=ok 1=抓取失败 2=文章被删/违规 3=解析失败 4=md不存在(--write) 5=反爬验证页 6=未知公众号
// 防封铁律: 伪装桌面 Chrome + 3 次退避重试 + 抖动 ×0.75~1.25; 失败显式非0, 不编数据
import fs from "node:fs";
import path from "node:path";

const ARGS = process.argv.slice(2);
const opt = (k) => { const i = ARGS.indexOf(k); return i === -1 ? null : ARGS[i + 1]; };
const URL_IN = opt("--url");
const DATE_IN = opt("--date");
const WRITE = ARGS.includes("--write");
const FORCE = ARGS.includes("--force");
if (!URL_IN && !ARGS.includes("--remount")) {
    console.error("用法: node scripts/wechat/fetch_wechat.mjs --url <url> [--date yyyy-MM-dd] [--write] [--force]\n      node scripts/wechat/fetch_wechat.mjs --remount --account <id> --date <d> [--write]  # 不重抓只重挂载(如 spec.md 更新后)");
    process.exit(1);
}
const REMOUNT = ARGS.includes("--remount");
const ACC_IN = opt("--account");

const ACCOUNTS = JSON.parse(fs.readFileSync(path.resolve("scripts/wechat/wechat_accounts.json"), "utf8"));
const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept-Language": "zh-CN,zh;q=0.9" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (base) => base * (0.75 + Math.random() * 0.5);

function decode(s) {
    return s.replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&#39;|&apos;/g, "'")
        .replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&hellip;/g, "…");
}
function pick(html, re) { const m = html.match(re); return m ? decode(m[1].trim()) : null; }

function parse(html) {
    if (/该内容已被发布者删除|此内容因违规无法查看|该公众号已被封禁/.test(html)) return { err: 2, msg: "文章被删/违规不可见" };
    if (/环境异常|完成验证后即可继续访问|操作频繁/.test(html)) return { err: 5, msg: "反爬验证页" };
    const title = pick(html, /<meta property="og:title" content="([^"]*)"/) || pick(html, /var msg_title = '([^']*)'/);
    const createTime = pick(html, /var createTime = '([^']*)'/) || pick(html, /<em id="publish_time"[^>]*>([^<]*)</);
    const nickname = pick(html, /var nickname = htmlDecode\("([^"]*)"\)/) || pick(html, /<span class="rich_media_meta_nickname[^"]*"[^>]*>\s*([^<]*?)\s*<\/span>/);
    const body = html.match(/<div class="rich_media_content[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<script/);
    if (!title || !body) return { err: 3, msg: `解析失败(title=${!!title} body=${!!body})` };
    const text = decode(body[1].replace(/<br[^>]*>/gi, "\n").replace(/<\/(p|section|h[1-6]|li)>/gi, "\n")
        .replace(/<[^>]+>/g, "")).replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (text.length < 50) return { err: 3, msg: `正文过短(${text.length}字), 疑解析错位` };
    return { title, createTime, nickname, text };
}

function mount(date, acc, meta, text) {
    const [y, m] = date.split("-");
    const md = path.join("md", `${y}S${Math.ceil(+m / 3)}`, `${date}.md`);
    if (!fs.existsSync(md)) return { code: 4, msg: "无md" };
    const lines = fs.readFileSync(md, "utf8").split("\n");
    // 找/补三级骨架: ## 盘前 → ### 微信公众号 → #### <name>
    let pi = lines.findIndex((l) => /^## /.test(l) && l.replace(/\s/g, "") === "##盘前");
    if (pi === -1) {
        const at = /^# /.test(lines[0] || "") ? 1 : 0;
        lines.splice(at, 0, "", "## 盘前", "");
        pi = at + 1;
    }
    let pEnd = lines.length;
    for (let i = pi + 1; i < lines.length; i++) if (/^## /.test(lines[i])) { pEnd = i; break; }
    let wi = -1;
    for (let i = pi + 1; i < pEnd; i++) if (/^### /.test(lines[i]) && lines[i].replace(/\s/g, "") === "###微信公众号") { wi = i; break; }
    if (wi === -1) { lines.splice(pEnd, 0, "### 微信公众号", ""); wi = pEnd; pEnd += 2; }
    let wEnd = pEnd;
    for (let i = wi + 1; i < pEnd; i++) if (/^#{2,3} /.test(lines[i])) { wEnd = i; break; }
    let hi = -1;
    for (let i = wi + 1; i < wEnd; i++) if (/^#### /.test(lines[i]) && lines[i].replace(/\s/g, "") === `####${acc.name.replace(/\s/g, "")}`) { hi = i; break; }
    const created = hi === -1;
    if (created) { lines.splice(wEnd, 0, `#### ${acc.name}`, ""); hi = wEnd; }
    let hEnd = lines.length;
    for (let i = hi + 1; i < lines.length; i++) if (/^#{2,4} /.test(lines[i])) { hEnd = i; break; }
    const old = lines.slice(hi + 1, hEnd);
    const carryReview = old.filter((l) => l.includes("【核销】"));
    const specFile = path.join("downloads", "wechat", acc.id, date, "spec.md");
    let specLines = null;
    if (fs.existsSync(specFile)) specLines = fs.readFileSync(specFile, "utf8").split("\n").map((l) => l.trimEnd()).filter((l) => l.trim());
    if (!specLines) specLines = old.filter((l) => l.includes("【推演要点】"));
    const block = [
        `#### ${acc.name}`, "",
        `> ${meta.title} · ${meta.createTime || date} · [原文链接](${meta.url})`, "",
    ];
    if (specLines.length) block.push(...specLines, "");
    if (carryReview.length) block.push(...carryReview, "");
    if (block[block.length - 1] !== "") block.push("");
    lines.splice(hi, hEnd - hi, ...block);
    fs.writeFileSync(md, lines.join("\n"));
    return { code: 0, msg: `${created ? "新建小节" : "覆盖"}(保${carryReview.length}核销/${specLines.length}推演)` };
}

(async () => {
    let acc, date, meta, text;
    if (REMOUNT) {
        acc = ACCOUNTS.find((a) => a.id === ACC_IN);
        if (!acc) { console.error("未知 --account"); process.exit(6); }
        date = DATE_IN;
        const dir = path.join("downloads", "wechat", acc.id, date);
        meta = JSON.parse(fs.readFileSync(path.join(dir, "meta.json"), "utf8"));
        text = fs.readFileSync(path.join(dir, "text.md"), "utf8");
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
        acc = ACCOUNTS.find((a) => p.nickname && p.nickname.replace(/\s/g, "").includes(a.name.replace(/\s/g, ""))) || ACCOUNTS.find((a) => a.id === ACC_IN);
        if (!acc) { console.error(`未知公众号"${p.nickname}", 先在 scripts/wechat/wechat_accounts.json 登记`); process.exit(6); }
        date = DATE_IN || (p.createTime || "").slice(0, 10) || new Date().toISOString().slice(0, 10);
        meta = { account: acc.id, name: acc.name, title: p.title, createTime: p.createTime, url: URL_IN, fetchedAt: new Date().toISOString(), chars: p.text.length };
        text = p.text;
        const dir = path.join("downloads", "wechat", acc.id, date);
        fs.mkdirSync(dir, { recursive: true });
        const mf = path.join(dir, "meta.json");
        if (!FORCE && fs.existsSync(mf)) console.log("产物已存在, 覆盖(同源性=当日重抓无害; 要保留旧件先备份)");
        fs.writeFileSync(path.join(dir, "raw.html"), html);
        fs.writeFileSync(path.join(dir, "text.md"), text);
        fs.writeFileSync(mf, JSON.stringify(meta, null, 2));
        console.log(`已抓: ${acc.name} | ${p.title} | ${p.createTime} | ${text.length}字 → ${dir}/`);
    }
    if (WRITE) {
        const r = mount(date, acc, meta, text);
        if (r.code) { console.error(`挂载失败: ${r.msg}`); process.exit(r.code); }
        console.log(`已挂载 md ${date}: ${r.msg}`);
    } else {
        console.log("(--write 才挂 md; 蒸馏后把【推演要点】写进产物目录 spec.md, 再 --remount --write)");
    }
    console.log(`JSON:${JSON.stringify({ account: acc.id, date, title: meta.title })}`);
})();
