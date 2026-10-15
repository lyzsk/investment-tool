// req_guard.mjs — 统一请求层(10/15 建, TODO §3-A2-2): 限速+抖动 / 滑动窗口 / 熔断 / 日预算 / 失败分类 / 每日计数
// 与 req_guard.py 接口一致、共读 req_guard_sources.json、共用 downloads/_guard/ 状态文件(跨进程/跨语言共享)。
// 用法(只换请求那一行, 业务逻辑不动):
//   import { gfetch, gcall, guard, ReqError, FAIL } from "../lib/req_guard.mjs";
//   const r = await gfetch(url, init);            // = fetch, 按域名自动路由到源; 返回原生 Response
//   const buf = await gcall(url, () => myHttpGet(url));   // 非 fetch 的请求(如 https 模块), 只做前置检查+失败分类
//   guard("lhb_id").ban("命中反爬页")               // 业务层识别到封禁特征时手动熔断; .fail(kind) 记业务失败(NO_DATA/PARSE)
// 语义: 熔断/冷却内直接抛 ReqError(BLOCKED) 不发请求; 超日预算/窗口满且等待超 maxWaitMs 抛 RATE_LIMIT(不发请求, 不计连败);
//   命中封禁特征(banStatus/banBody)=立即写 <id>.ban.json 冷却 banCoolMin; 连败 breakN 次(BLOCKED/UNAVAILABLE/服务端限流)=冷却 coolMin;
//   冷却过后下一次请求即探测, 成功则删 ban 文件(历史进 ban_history.jsonl)。
//   环境变量 REQ_GUARD_PROBE=<id>[,<id>]|all: 冷却中也放行(人工探测)。守卫自身的文件读写出错一律吞掉, 绝不因记账挡住请求。
// 状态文件: downloads/_guard/<id>.ban.json(熔断) / <id>.state.json(连败/上次请求/窗口) / <id>_requests_<日>.json(当日计数)
// CLI: node scripts/lib/req_guard.mjs --status | --clear <id>
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const GUARD_DIR = path.resolve(HERE, "../../downloads/_guard");
const CONF = JSON.parse(fs.readFileSync(path.join(HERE, "req_guard_sources.json"), "utf8"));
export const FAIL = Object.freeze({ BLOCKED: "BLOCKED", AUTH: "AUTH", RATE_LIMIT: "RATE_LIMIT", NO_DATA: "NO_DATA", UNAVAILABLE: "UNAVAILABLE", PARSE: "PARSE" });
export class ReqError extends Error {
    constructor(kind, msg, extra = {}) { super(`[${kind}] ${msg}`); this.name = "ReqError"; this.kind = kind; Object.assign(this, extra); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const today = () => new Date().toLocaleDateString("sv-SE");
const rd = (f, d) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return d; } };
function wr(f, obj) {   // 原子写(临时文件+改名); 失败退化直写; 再失败吞掉
    try {
        fs.mkdirSync(GUARD_DIR, { recursive: true });
        const tmp = `${f}.${process.pid}.tmp`;
        fs.writeFileSync(tmp, JSON.stringify(obj));
        try { fs.renameSync(tmp, f); } catch { fs.writeFileSync(f, JSON.stringify(obj)); try { fs.unlinkSync(tmp); } catch { /* */ } }
    } catch { /* 记账失败不挡请求 */ }
}
const probeAllowed = (id) => { const p = (process.env.REQ_GUARD_PROBE || "").split(","); return p.includes("all") || p.includes(id); };

// 失败分类: 先看 HTTP 状态/响应体, 再看异常
export function classify({ status = 0, text = "", err = null } = {}, cfg = CONF._default) {
    if (err) {
        const m = String(err?.message || err) + " " + String(err?.cause?.code || err?.code || "");
        const hs = m.match(/HTTP (\d{3})/);
        if (hs) return classify({ status: +hs[1], text }, cfg);
        if (err.name === "SyntaxError" || /JSON|Unexpected token/.test(m)) return { kind: FAIL.PARSE };
        return { kind: FAIL.UNAVAILABLE };   // 超时/断连/DNS/ECONNRESET(东财封 IP 也是这个形态)
    }
    if ((cfg.banStatus || []).includes(status)) return { kind: FAIL.BLOCKED, ban: true, why: `HTTP ${status}` };
    const hit = text && (cfg.banBody || []).find((p) => text.includes(p));
    if (hit) return { kind: FAIL.BLOCKED, ban: true, why: `命中封禁特征 ${hit}` };
    if (status === 401) return { kind: FAIL.AUTH };
    if (status === 403 || status === 412) return { kind: FAIL.BLOCKED };   // 非封禁特征的 403/412 计连败(B站 412 间歇, 10/15 实测)
    if (status === 429) return { kind: FAIL.RATE_LIMIT };
    if (status === 404 || status === 204) return { kind: FAIL.NO_DATA };
    if (status >= 500 || status === 0) return { kind: FAIL.UNAVAILABLE };
    if (status >= 400) return { kind: FAIL.UNAVAILABLE };
    return null;
}
const STREAK = new Set([FAIL.BLOCKED, FAIL.UNAVAILABLE, FAIL.RATE_LIMIT]);   // 计入连败的类型(AUTH/NO_DATA/PARSE 冷却也没用, 不计)

export class Guard {
    constructor(id, cfg) {
        this.id = id; this.cfg = cfg;
        this.fBan = path.join(GUARD_DIR, `${id}.ban.json`);
        this.fState = path.join(GUARD_DIR, `${id}.state.json`);
    }
    get fCount() { return path.join(GUARD_DIR, `${this.id}_requests_${today()}.json`); }
    banned() {
        const b = rd(this.fBan, null);
        return b && Date.parse(b.until) > Date.now() ? b : null;
    }
    _count(fn) {
        const c = rd(this.fCount, null) || { id: this.id, date: today(), n: 0, ok: 0, fail: {}, budget: this.cfg.dayBudget };
        fn(c); c.budget = this.cfg.dayBudget; c.lastAt = new Date().toISOString();
        wr(this.fCount, c);
        return c;
    }
    // 前置: 熔断 → 日预算 → 窗口/间隔(跨进程) ; 通过后登记一次请求
    async _pre(opt = {}) {
        const b = this.banned();
        if (b && !probeAllowed(this.id)) throw new ReqError(FAIL.BLOCKED, `${this.id} 熔断中(${b.kind}: ${b.info}) 至 ${b.until}, 不发请求`, { source: this.id, local: true });
        const c = rd(this.fCount, { n: 0 });
        if (c.n >= this.cfg.dayBudget) throw new ReqError(FAIL.RATE_LIMIT, `${this.id} 今日请求 ${c.n} 已达预算 ${this.cfg.dayBudget}`, { source: this.id, local: true });
        const maxWait = opt.maxWaitMs ?? this.cfg.maxWaitMs;
        for (let guardLoop = 0; ; guardLoop++) {
            const st = rd(this.fState, {}), now = Date.now();
            let wait = 0;
            if (this.cfg.gapMs) {
                const gap = this.cfg.gapMs * (1 - this.cfg.jitter + Math.random() * 2 * this.cfg.jitter);
                wait = Math.max(wait, (st.lastAt || 0) + gap - now);
            }
            const win = (st.win || []).filter((t) => t > now - (this.cfg.winSec || 0) * 1000);
            if (this.cfg.winN && win.length >= this.cfg.winN) wait = Math.max(wait, win[0] + this.cfg.winSec * 1000 - now + 50);
            if (wait <= 0 || guardLoop > 50) {
                st.lastAt = now;
                if (this.cfg.winN) st.win = [...win, now];
                wr(this.fState, st);
                break;
            }
            if (wait > maxWait) throw new ReqError(FAIL.RATE_LIMIT, `${this.id} 限速: 需等 ${(wait / 1000).toFixed(0)}s > 上限 ${(maxWait / 1000).toFixed(0)}s, 本次不发`, { source: this.id, local: true });
            await sleep(Math.min(wait, 5000));
        }
        this._count((x) => { x.n++; });
    }
    ok() {
        this._count((x) => { x.ok++; });
        const st = rd(this.fState, {});
        if (st.streak) { st.streak = 0; wr(this.fState, st); }
        if (fs.existsSync(this.fBan)) {   // 冷却后探测成功=解除
            const b = rd(this.fBan, {});
            try { fs.appendFileSync(path.join(GUARD_DIR, "ban_history.jsonl"), JSON.stringify({ ...b, cleared: new Date().toISOString() }) + "\n"); fs.unlinkSync(this.fBan); } catch { /* */ }
        }
    }
    // 记一次失败; ban=true 立即熔断; 连败到 breakN 熔断 coolMin
    fail(kind, info = "", { ban = false, coolMin = null } = {}) {
        this._count((x) => { x.fail[kind] = (x.fail[kind] || 0) + 1; x.lastFail = `${kind} ${String(info).slice(0, 160)}`; });
        if (ban) return this.ban(info, coolMin ?? this.cfg.banCoolMin, kind);
        if (!STREAK.has(kind)) return;
        const st = rd(this.fState, {});
        st.streak = (st.streak || 0) + 1;
        wr(this.fState, st);
        if (st.streak >= this.cfg.breakN) this.ban(`连败 ${st.streak} 次, 末次 ${kind} ${info}`, coolMin ?? this.cfg.coolMin, kind);
    }
    ban(info = "", coolMin = null, kind = FAIL.BLOCKED) {
        const m = coolMin ?? this.cfg.banCoolMin;
        const at = new Date();
        const c = rd(this.fCount, { n: 0 });
        wr(this.fBan, { id: this.id, kind, info: String(info).slice(0, 200), at: at.toISOString(), until: new Date(at.getTime() + m * 60e3).toISOString(), coolMin: m, reqToday: c.n });
        const st = rd(this.fState, {}); st.streak = 0; wr(this.fState, st);
        try { console.error(`[req_guard] ${this.id} 熔断 ${m} 分钟: ${kind} ${String(info).slice(0, 120)}`); } catch { /* */ }
    }
    // fetch 直替: 返回原生 Response; 封禁特征/失败已记账; 命中封禁特征时抛 BLOCKED(与原先"非 JSON/风控页抛错"同向)
    async fetch(url, init = {}, opt = {}) {
        await this._pre(opt);
        let r;
        try {
            r = await fetch(url, init.signal ? init : { ...init, signal: AbortSignal.timeout(opt.timeoutMs || this.cfg.timeoutMs) });
        } catch (e) {
            const k = classify({ err: e }, this.cfg);
            this.fail(k.kind, `${e.message} ${e.cause?.code || ""} ${String(url).slice(0, 80)}`);
            throw e;   // 原样抛(调用方原有 catch/降级逻辑不变)
        }
        let text = "";
        const ct = r.headers.get("content-type") || "";
        if (!r.ok || ((this.cfg.banBody || []).length && (!ct || /json|text|html|javascript|xml/i.test(ct)))) {
            try { text = await r.clone().text(); } catch { /* */ }
        }
        const k = classify({ status: r.status, text }, this.cfg);
        if (!k) { this.ok(); return r; }
        this.fail(k.kind, `${k.why || "HTTP " + r.status} ${String(url).slice(0, 80)}`, { ban: !!k.ban });
        if (k.ban) throw new ReqError(FAIL.BLOCKED, `${this.id} ${k.why}: ${text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 100)}`, { source: this.id, status: r.status });
        return r;
    }
    // 非 fetch 请求: fn 自己发, 守卫做前置+按异常分类记账(异常原样抛)
    async call(fn, opt = {}) {
        await this._pre(opt);
        try {
            const v = await fn();
            this.ok();
            return v;
        } catch (e) {
            const k = classify({ err: e }, this.cfg);
            this.fail(k.kind, `${e.message} ${opt.url ? String(opt.url).slice(0, 80) : ""}`, { ban: !!k.ban });
            throw e;
        }
    }
}

const CACHE = new Map();
export function guard(id, override = {}) {
    if (!CACHE.has(id) || Object.keys(override).length) {
        const g = new Guard(id, { ...CONF._default, ...(CONF.sources[id] || {}), ...override });
        if (Object.keys(override).length) return g;
        CACHE.set(id, g);
    }
    return CACHE.get(id);
}
export function sourceOf(url) {
    let host = "", hp = "";
    try { const u = new URL(url); host = u.hostname; hp = host + u.pathname; } catch { return "_other"; }
    let best = null;
    for (const [id, c] of Object.entries(CONF.sources)) {
        for (const h of c.hosts || []) {   // 含 "/" = 域名+路径前缀(同域不同接口分开熔断, 如 push2 clist 与 stock/get)
            const hit = h.includes("/") ? hp.startsWith(h) : h.startsWith(".") ? host.endsWith(h) || host === h.slice(1) : host === h;
            if (hit && (!best || h.length > best.len)) best = { id, len: h.length };   // 最长匹配: push2.eastmoney.com 优先于 .eastmoney.com
        }
    }
    return best ? best.id : "_other";
}
export const gfetch = (url, init = {}, opt = {}) => guard(opt.source || sourceOf(url)).fetch(url, init, opt);
export const gcall = (url, fn, opt = {}) => guard(opt.source || sourceOf(url)).call(fn, { ...opt, url });

// 巡检用: 当前熔断 + 当日计数
export function guardStatus() {
    const out = { bans: [], counters: [] };
    let files = [];
    try { files = fs.readdirSync(GUARD_DIR); } catch { return out; }
    for (const f of files) {
        if (f.endsWith(".ban.json")) { const b = rd(path.join(GUARD_DIR, f), null); if (b) out.bans.push({ ...b, active: Date.parse(b.until) > Date.now() }); }
        const m = f.match(/^(.+)_requests_(\d{4}-\d\d-\d\d)\.json$/);
        if (m && m[2] === today()) out.counters.push(rd(path.join(GUARD_DIR, f), {}));
    }
    return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    const a = process.argv.slice(2);
    if (a[0] === "--clear" && a[1]) {
        const g = guard(a[1]);
        if (fs.existsSync(g.fBan)) { fs.appendFileSync(path.join(GUARD_DIR, "ban_history.jsonl"), JSON.stringify({ ...rd(g.fBan, {}), cleared: new Date().toISOString(), by: "manual" }) + "\n"); fs.unlinkSync(g.fBan); }
        console.log(`cleared ${a[1]}`);
    } else if (a[0] === "--route" && a[1]) {
        console.log(sourceOf(a[1]));
    } else {
        console.log(JSON.stringify(guardStatus(), null, 1));
    }
}
