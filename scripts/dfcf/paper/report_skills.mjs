// report_skills.mjs — report.html 的「skill 多维对比」+「做 T 品种 skill」两张卡(零 token, 10/18 晚用户令: 更多维度看和比较各个 skill, 含新增的银行股 / 纳指 skill)
// 只读现成产物, 缺哪项就显示 —, 不现算重活:
//   paper 表现 = report 合并时间轴(回放+实盘连乘) / 对比 = 导师真人净值 + 对照组 + similarity.json 拟人度
//   真人近 60 日 = scripts/tzzb/mentor_cards/<最新>.json / 做 T = scripts/dfcf/paper/t_profile/<最新>.json
//   skill 厚度 = skills/<id>-skill/persona/{rules,cases}.md + case_log/*.md(日卡) + case_log/annotations.jsonl(解读) / 版本 = skills_versions/<id>/index.json
//   成本 = scripts/dfcf/paper/token_log.csv(链, 近 5 个实盘日日均) + scripts/lib/claude_cost.csv(建设: 蒸馏/加厚/解读/修复等 tag 带 :<id> 的累计)
//   做 T 三本 = books/A-{d,t,h}{bank,ndq}.json + t_log/*.json + t_decide_state.json
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..", "..");
const SK = path.join(ROOT, "skills");
const rd = (f) => { try { return fs.readFileSync(f, "utf8"); } catch { return null; } };
const rj = (f) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return null; } };
const latest = (dir, re = /^20\d\d-\d\d-\d\d\.json$/) => { try { return fs.readdirSync(dir).filter((f) => re.test(f)).sort().map((f) => path.join(dir, f)); } catch { return []; } };
const count = (s, re) => (s ? (s.match(re) || []).length : null);
const skillOf = (src) => (src === "A-cb" ? "buchitudou0" : src.replace(/^A-/, ""));

function thickness(id) {
    const p = path.join(SK, `${id}-skill`, "persona");
    const rules = rd(path.join(p, "rules.md")), cases = rd(path.join(p, "cases.md"));
    let days = null, ann = null, tdays = null;
    const cl = path.join(p, "case_log");
    if (fs.existsSync(cl)) {
        days = 0;
        tdays = new Set();
        for (const f of fs.readdirSync(cl)) if (/^20\d\d-\d\d\.md$/.test(f)) for (const m of rd(path.join(cl, f)).matchAll(/^### (20\d\d-\d\d-\d\d)[^|\n]*\|\s*([^/\n]*)/gm)) {
            days++;
            if (!/^(持仓不动|收盘满仓|空仓|—|疑似出金|疑似入金|仓位变动无成交明细)\s*$/.test(m[2].trim())) tdays.add(m[1]);   // 10/19: 没成交的日卡本来就不解读, 不进覆盖率分母; "仓位变动无成交明细" = 账本没给成交明细, 无从解读(数据缺口)
        }
        const a = rd(path.join(cl, "annotations.jsonl"));
        const aset = a ? new Set(a.split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l).date; } catch { return null; } }).filter(Boolean)) : new Set();
        ann = [...aset].filter((d) => tdays.has(d)).length;
    }
    const st = (k) => count(rules, new RegExp(`时间状态.*状态 ${k}`, "g"));
    const vi = rj(path.join(ROOT, "skills_versions", id, "index.json"));
    return { rules: count(rules, /^#{3,4} +[A-Z]{0,2}\d+/gm) || count(rules, /^- \*\*[A-Z]{0,2}\d+/gm), cases: count(cases, /^### /gm), days, ann, tdays: tdays ? tdays.size : null, cov: tdays && tdays.size ? ann / tdays.size : null,   // tzzb/品种=### R1 标题; UP=### A1 或 - **B1** 列表
        active: st("活跃"), stale: st("待复核"), neg: st("已否定"), versions: vi?.versions?.length ?? null };
}

function costs() {
    const chain = {}, build = {};
    const tl = rd(path.join(HERE, "token_log.csv"));
    if (tl) {
        const rows = tl.split("\n").slice(1).map((l) => l.split(",")).filter((c) => c.length >= 9 && c[11] !== "1" && c[8]);
        const by = {};   // 每条链按它自己最近 5 个实盘日平均(晚上线的链不被稀释)
        for (const c of rows) ((by[c[8]] ||= {})[c[0]] = (by[c[8]][c[0]] || 0) + (+c[6] || 0));
        for (const [k, d] of Object.entries(by)) { const ds = Object.keys(d).sort().slice(-5); chain[k] = ds.reduce((a, x) => a + d[x], 0) / ds.length; }
    }
    const cc = rd(path.join(ROOT, "scripts", "lib", "claude_cost.csv"));
    if (cc) for (const l of cc.split("\n").slice(1)) {
        const c = l.split(","), m = /:([a-z0-9]+)/.exec(c[1] || "");
        if (m) build[m[1]] = (build[m[1]] || 0) + (+c[11] || 0);
    }
    return { chain, build };
}

function perfOf(pts) {
    const p = (pts || []).filter((x) => x && x.cum != null);
    if (!p.length) return null;
    const days = p.map((x) => x.day).filter((x) => x != null);
    const mean = days.reduce((a, x) => a + x, 0) / (days.length || 1);
    const sd = Math.sqrt(days.reduce((a, x) => a + (x - mean) ** 2, 0) / (days.length || 1));
    let peak = 1, mdd = 0;
    for (const x of p) { peak = Math.max(peak, 1 + x.cum); mdd = Math.min(mdd, (1 + x.cum) / peak - 1); }
    return { cum: p.at(-1).cum, mean, sd, win: days.filter((x) => x > 0).length / (days.length || 1), mdd, n: days.length };
}

// ---- 卡 1: skill 多维对比 ----
export function skillMatrixSection({ merged, accounts, esc, sign, tzUrl }) {
    const ex = rj(path.join(ROOT, "scripts", "tzzb", "paper_excluded.json"))?.excluded || {};
    const cardsF = latest(path.join(ROOT, "scripts", "tzzb", "mentor_cards")).at(-1);
    const cards = (cardsF && rj(cardsF)?.cards) || {};
    const tpF = latest(path.join(HERE, "t_profile")).at(-1);
    const tp = (tpF && rj(tpF)?.mentors) || {};
    const sim = Object.fromEntries((rj(path.join(HERE, "similarity.json"))?.summary || []).map((x) => [x.book, x]));
    const RB = rj(path.join(HERE, "rand_baseline.json"))?.chains || {};   // 10/18 晚 P0: RAND 抛硬币基准
    const { chain, build } = costs();
    const ctrl = perfOf(merged.series.find((s) => s.kind === "对照")?.pts);
    const rows = merged.series.filter((s) => !["混合", "做T"].includes(s.kind)).map((s) => {
        const id = skillOf(s.src), P = perfOf(s.pts), mp = perfOf(s.mentor), c = cards[id]?.card, t = tp[id]?.long, th = thickness(id);
        const perf = (k) => (c?.perf || []).find((x) => x.includes(k));
        const pct = (str) => (str ? +(/([+-−]?\d+(\.\d+)?)%/.exec(str)?.[1]?.replace("−", "-")) / 100 : null);
        const cashAvg = (() => { const a = accounts.find((x) => x.src === s.src); const n = (a?.b.nav || []).filter((x) => x.date >= "2026-10-08" && x.nav); return n.length ? n.reduce((t2, x) => t2 + x.cash / x.nav, 0) / n.length : null; })();
        const nTr = accounts.find((x) => x.src === s.src)?.b.trades.length ?? null;
        return { s, id, status: s.kind === "对照" ? "对照" : ex[id] ? "退出paper" : "在跑", style: (c?.style || []).slice(0, 4).join("·"),
            P, vsM: P && mp ? P.cum - mp.cum : null, vsC: P && ctrl && s.kind !== "对照" ? P.cum - ctrl.cum : null, mimic: sim[s.src]?.comp ?? null, mimicD: sim[s.src]?.delta ?? null, rpct: RB[id]?.lots ? RB[id].pct : null,
            m30: c?.ret30 ?? null, m60dd: c?.mdd ?? null, mwin: pct(perf("胜率")), mpos: c?.avg_pos != null ? c.avg_pos / 100 : null,
            trades: nTr, cash: cashAvg, tFreq: t?.freq ?? null, tWin: t?.t_days ? t.win : null, tRet: t?.t_days ? t.ret_mean : null, tVerdict: tp[id]?.verdict || tp[id]?.label || "",
            ...th, cChain: chain[id] ?? null, cBuild: build[id] ?? null };
    });
    const P = (x, d = 1) => (x == null || Number.isNaN(x) ? null : sign(x, d));
    const cell = (v, txt, g, cls = "") => `<td class="num ${cls}" data-g="${g}" data-v="${v ?? ""}">${txt ?? `<span class="muted">—</span>`}</td>`;
    const ud = (x) => (x > 0 ? "up" : x < 0 ? "dn" : "");
    const usd = (x) => (x == null ? null : "$" + x.toFixed(x < 10 ? 2 : 0));
    const G = [["id", "身份"], ["perf", "paper 表现"], ["cmp", "对比"], ["real", "真人近 60 日"], ["beh", "行为"], ["t", "真人做 T"], ["thick", "skill 厚度"], ["cost", "成本"]];
    const cols = [["perf", "累计"], ["perf", "日均"], ["perf", "日胜率"], ["perf", "日波动"], ["perf", "最大回撤"],
        ["cmp", "相对真人(同期)"], ["cmp", "相对对照组"], ["cmp", "拟人度"], ["cmp", "skill−对照"], ["cmp", "跑赢随机(分位)"],
        ["real", "近30日"], ["real", "60日回撤"], ["real", "新开仓次日胜率"], ["real", "平均仓位"],
        ["beh", "成交笔数"], ["beh", "平均现金占比"],
        ["t", "做T频率"], ["t", "做T胜率"], ["t", "每次均"], ["t", "判定"],
        ["thick", "规则"], ["thick", "叙事案例"], ["thick", "日卡天数"], ["thick", "已解读"], ["thick", "解读覆盖"], ["thick", "活跃/待复核/否定"], ["thick", "版本数"],
        ["cost", "链日均(近5日)"], ["cost", "建设累计"]];
    const head = `<tr><th data-g="id">skill</th><th data-g="id">状态</th><th data-g="id">风格(真人近 60 日机械标签)</th>${cols.map(([g, n], i) => `<th class="num${n === "判定" ? "" : " sortable"}" data-g="${g}" data-c="${i + 3}">${n}</th>`).join("")}</tr>`;
    const tzA = (r) => { const u = tzUrl && tzUrl(r.s.src); return u ? ` <a class="small" href="${u}" target="_blank" rel="noopener" title="导师真人同花顺投资账本">tzzb↗</a>` : ""; };
    const body = rows.map((r) => `<tr${r.status === "退出paper" ? ' data-off="1"' : ""}><td data-g="id">${esc(r.s.name)}<span class="muted small"> ${r.id}</span>${tzA(r)}</td><td data-g="id">${r.status === "在跑" ? r.status : `<span class="muted">${r.status}</span>`}</td><td data-g="id" class="muted small">${esc(r.style)}</td>`
        + cell(r.P?.cum, P(r.P?.cum, 2), "perf", ud(r.P?.cum)) + cell(r.P?.mean, P(r.P?.mean, 2), "perf", ud(r.P?.mean)) + cell(r.P?.win, r.P ? (r.P.win * 100).toFixed(0) + "%" : null, "perf")
        + cell(r.P?.sd, r.P ? (r.P.sd * 100).toFixed(2) + "%" : null, "perf") + cell(r.P?.mdd, P(r.P?.mdd), "perf")
        + cell(r.vsM, P(r.vsM), "cmp", ud(r.vsM)) + cell(r.vsC, P(r.vsC), "cmp", ud(r.vsC)) + cell(r.mimic, r.mimic == null ? null : (r.mimic * 100).toFixed(0) + "%", "cmp") + cell(r.mimicD, P(r.mimicD, 0), "cmp", ud(r.mimicD)) + cell(r.rpct, r.rpct == null ? null : (r.rpct * 100).toFixed(0) + "%", "cmp", r.rpct == null ? "" : r.rpct >= 0.8 ? "up" : r.rpct <= 0.2 ? "dn" : "")
        + cell(r.m30, P(r.m30, 0), "real", ud(r.m30)) + cell(r.m60dd, P(r.m60dd, 0), "real") + cell(r.mwin, r.mwin == null ? null : (r.mwin * 100).toFixed(0) + "%", "real") + cell(r.mpos, r.mpos == null ? null : (r.mpos * 100).toFixed(0) + "%", "real")
        + cell(r.trades, r.trades, "beh") + cell(r.cash, r.cash == null ? null : (r.cash * 100).toFixed(0) + "%", "beh")
        + cell(r.tFreq, r.tFreq == null ? null : (r.tFreq * 100).toFixed(0) + "%", "t") + cell(r.tWin, r.tWin == null ? null : (r.tWin * 100).toFixed(0) + "%", "t") + cell(r.tRet, P(r.tRet, 2), "t", ud(r.tRet)) + `<td data-g="t" class="small">${esc(r.tVerdict)}</td>`
        + cell(r.rules, r.rules, "thick") + cell(r.cases, r.cases, "thick") + cell(r.days, r.days, "thick") + cell(r.ann, r.ann, "thick") + cell(r.cov, r.cov == null ? null : (r.cov * 100).toFixed(0) + "%", "thick")
        + cell(r.active, r.rules ? `${r.active ?? 0}/${r.stale ?? 0}/${r.neg ?? 0}` : null, "thick") + cell(r.versions, r.versions, "thick")
        + cell(r.cChain, usd(r.cChain), "cost") + cell(r.cBuild, usd(r.cBuild), "cost") + "</tr>").join("");
    const chips = G.map(([g, n]) => `<button class="btn dim-g${["id", "perf", "cmp", "thick"].includes(g) ? " on" : ""}" data-g="${g}"${g === "id" ? " disabled" : ""}>${n}</button>`).join("");
    return `<div class="card"><h2>skill 多维对比 <span class="muted small">(${rows.length} 个 skill; 点表头排序, 点维度按钮显示/隐藏一组列; — = 该项暂无数据)</span></h2>`
        + `<div class="toolbar"><span class="muted small">维度</span>${chips}<button class="btn" id="dim-all">全部</button></div>`
        + `<div class="scroll" style="max-height:560px"><table class="t" id="skm">${head}${body}</table></div>`
        + `<p class="legend-note"><b>paper 表现</b>按走势图同一条合并时间轴(9/28 起回放 + 10/8 起实盘连乘); <b>相对真人</b>=同期 paper 累计 − 导师真人净值累计(UP / 对照组无账本 = —); <b>拟人度</b>=similarity.json 滚动窗口; <b>跑赢随机</b>=RAND 抛硬币基准(rand_baseline.py: 买卖日期 / 金额照抄该链, 只把"买哪只"换成当天候选池随机一只, 几百次随机里该链排第几百分位; 50%=和运气一样, 样本少时只看方向);
<b>真人近 60 日</b>=导师名片(mentor_cards, 每晚重算); <b>真人做 T</b>=t_profile 全历史(频率=做 T 日 / 出手日); <b>skill 厚度</b>: 日卡=全量操作日志卡天数, 已解读=日卡解读天数, 覆盖=已解读 / 有成交的日卡(持仓不动、空仓、只有资金进出的日卡本来就不解读, 10/19 起不进分母); UP 三人日卡解读还没开始(10/19 晚试跑桃哥), 所以是 0%;
<b>成本</b>: 链日均=token_log 近 5 个实盘日该链平均花费, 建设累计=蒸馏 / 加厚 / 日卡解读 / 推测层修复等一次性花费合计(claude_cost.csv 按 tag 归属)。退出 paper 的导师只保留历史数据, 不再花 token。</p></div>`;
}

// ---- 卡 2: 做 T 品种 skill(银行股 / 纳指), 每个品种 决策T / 机械T / 不T 三本 ----
export function tSkillSection({ esc, sign }) {
    const books = (s) => rj(path.join(HERE, "books", s + ".json"));
    const state = rj(path.join(HERE, "t_decide_state.json")) || {};
    const logs = latest(path.join(HERE, "t_log")).map((f) => rj(f)).filter(Boolean);
    const CAP = 10000, RES = 90000;
    const ud = (x) => (x > 0 ? "up" : x < 0 ? "dn" : "");
    const G = [["bank", "银行股 skill", "中国银行 601988", { dec: "A-dbank", mech: "A-tbank", hold: "A-hbank" }, "601988"],
        ["nasdaq", "纳指 skill", "纳指ETF(广发) 159941", { dec: "A-dndq", mech: "A-tndq", hold: "A-hndq" }, "159941"]];
    const blocks = G.map(([id, title, inst, B, code]) => {
        const th = thickness(id);
        const prof = rd(path.join(SK, `${id}-skill`, "persona", "profile.md")) || "";
        const r30 = /\| 近 30 日 \| ([^|]+) \| ([^|]+) \| ([^|]+) \|/.exec(prof);
        const m250 = /\| 近 250 日 \| \d+ \| (\d+%) \|[^\n]*\| ([^|]+) \|\s*$/m.exec(prof.split("**③")[0]);
        const hold = books(B.hold), holdNav = hold?.nav?.at(-1)?.nav;
        const rows = [["决策T(花 token)", B.dec], ["机械T(零 token)", B.mech], ["不T(只拿底仓)", B.hold]].map(([n, src]) => {
            const b = books(src);
            if (!b) return `<tr><td>${n}</td><td colspan="8" class="muted">账本缺</td></tr>`;
            const nav = b.nav?.at(-1)?.nav ?? b.cash, trades = b.trades || [];
            const tDays = new Set(trades.map((t) => String(t.id).slice(0, 10)).filter((d) => trades.some((t) => String(t.id).startsWith(d) && t.side === "BUY") && trades.some((t) => String(t.id).startsWith(d) && t.side === "SELL"))).size;
            const fee = trades.reduce((a, t) => a + (+t.fee || 0), 0);
            const tok = src === B.dec ? Object.values(state).reduce((a, d) => a + Object.values(d[src] || {}).reduce((x, v) => x + (+v?.cost || 0), 0), 0) : 0;
            const pos = +((b.positions || {})[code]?.qty || 0);
            return `<tr><td>${n}<span class="muted small"> ${src}</span></td><td class="num ${ud(nav - 100000)}"><b>${b.nav?.length ? sign((nav - 100000) / CAP, 2) : "—"}</b></td>`
                + `<td class="num ${ud(nav - (holdNav ?? nav))}">${b.nav?.length && holdNav ? (nav - holdNav >= 0 ? "+" : "−") + Math.abs(nav - holdNav).toFixed(0) + " 元" : "—"}</td>`
                + `<td class="num">${pos || "—"}</td><td class="num">${b._t_base || "—"}</td><td class="num">${trades.length}</td><td class="num">${tDays}</td><td class="num">${fee ? fee.toFixed(1) + " 元" : "—"}</td><td class="num">${tok ? "$" + tok.toFixed(2) : src === B.dec ? "$0" : "0"}</td></tr>`;
        }).join("");
        const L = logs.filter((x) => x.best?.[code]);
        const avg = (k) => (L.length ? L.reduce((a, x) => a + (x.best[code][k]?.spread || 0), 0) / L.length : null);
        const decDays = Object.entries(state).filter(([, d]) => d[B.dec] && Object.keys(d[B.dec]).some((k) => /^\d{4}$/.test(k))).length;
        return `<div style="flex:1;min-width:460px"><h3 style="font-size:13px;margin:6px 0">${title} <span class="muted small">· ${inst} · ${esc(`规则 ${th.rules ?? 0} 条 / 日卡 ${th.cases ?? 0} 张 / 版本 ${th.versions ?? 0}`)}</span></h3>`
            + `<div class="scroll"><table class="t"><tr><th>账本</th><th class="num">收益(相对 1 万)</th><th class="num">相对不T</th><th class="num">持仓</th><th class="num">底仓</th><th class="num">成交笔数</th><th class="num">做T天数</th><th class="num">费用合计</th><th class="num">token</th></tr>${rows}</table></div>`
            + `<p class="legend-note">品种数据(t_skill.py, 日线): 近 30 日 最高涨幅中位 ${r30 ? esc(r30[1].trim()) : "—"} / 最大跌幅中位 ${r30 ? esc(r30[2].trim()) : "—"} / 日内区间中位 ${r30 ? esc(r30[3].trim()) : "—"};
机械 T 近 250 日两边都成交 ${m250 ? m250[1] : "—"}、成交时扣真实费用后价差中位 ${m250 ? esc(m250[2].trim()) : "—"}。
复盘: ${L.length ? `${L.length} 天, 事后最优 正T 均 ${sign(avg("正T"), 2)} / 反T 均 ${sign(avg("反T"), 2)}` : "还没有(10/19 建底仓, 10/20 起开始 T, 每天收盘 t_review.py 写日卡)"}; 决策T 已决策 ${decDays} 天。</p></div>`;
    }).join("");
    return `<div class="card"><h2>做 T 品种 skill <span class="muted small">(银行股 / 纳指; 每个品种三本对照: 决策T 读全体 skill 做 T 知识 / 机械T 按振幅挂单 / 不T 只拿底仓; 账本 10 万开户但只动 1 万(按你的计划), 费用按你券商实收: 每笔最低 5 元)</span></h2>`
        + `<div style="display:flex;gap:16px;flex-wrap:wrap">${blocks}</div>`
        + `<p class="legend-note"><b>收益(相对 1 万)</b>=(净值 − 10 万)/1 万; <b>相对不T</b>=本账本净值 − 不T 账本净值(元), 决策T / 机械T 跑赢不T 才说明 T 有用; <b>做T天数</b>=同日既买又卖的天数; <b>token</b>=决策T 调模型累计花费(机械 / 不T 为 0)。跑满 20 个交易日再下结论。</p></div>`;
}

// 页面脚本: 维度按钮 + 表头排序(注入 report 模板 <script> 末尾)
export const SKILL_JS = `
(function(){const t=document.getElementById("skm");if(!t)return;
const show=g=>[...t.querySelectorAll('[data-g="'+g+'"]')].forEach(e=>e.style.display="");const hide=g=>[...t.querySelectorAll('[data-g="'+g+'"]')].forEach(e=>e.style.display="none");
const btns=[...document.querySelectorAll("button.dim-g")];const sync=()=>btns.forEach(b=>b.classList.contains("on")?show(b.dataset.g):hide(b.dataset.g));
btns.forEach(b=>{if(b.disabled)return;b.onclick=()=>{b.classList.toggle("on");sync();};});
document.getElementById("dim-all").onclick=()=>{btns.forEach(b=>b.classList.add("on"));sync();};sync();
let last=null,dir=-1;t.querySelectorAll("th.sortable").forEach(th=>{th.style.cursor="pointer";th.title="点击排序";th.onclick=()=>{const c=+th.dataset.c;dir=last===c?-dir:-1;last=c;
const rows=[...t.querySelectorAll("tr")].slice(1);rows.sort((a,b)=>{const x=a.children[c].dataset.v,y=b.children[c].dataset.v;if(x===""&&y==="")return 0;if(x==="")return 1;if(y==="")return -1;return dir*(parseFloat(x)-parseFloat(y));});
rows.forEach(r=>t.appendChild(r));t.querySelectorAll("th.sortable").forEach(h=>h.textContent=h.textContent.replace(/ [▲▼]$/,""));th.textContent+=dir<0?" ▼":" ▲";};});})();`;
