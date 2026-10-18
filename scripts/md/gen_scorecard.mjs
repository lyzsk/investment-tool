// gen_scorecard.mjs — md 核销行 → 信号源记分卡(零 token 机械层, 2026-10-02)
// 用途: 盘中调用 skill 时的"可评价标准"——把散在 md 里的【核销 T+1】聚合成
//       全量/近20日 两窗口的命中率, 供 01 facts 加权与 hermes 读权重
// 用法: node scripts/md/gen_scorecard.mjs [--src fage]
// 产物: skills/<src>-skill/persona/score.json(覆盖重写, 内容即状态: md 核销行=唯一事实源)
// 口径: 命中=1 半命中=0.5 打脸=0 不可证不计入; 纯命中率=命中/可判定; 含半=(命中+0.5*半)/可判定
// 扩展: 新增信号源=其核销行需同格式 【核销 T+1】命中x 半命中x 打脸x 不可证x, 并在 SRCS 登记小节名
import fs from "node:fs";
import path from "node:path";

const SRCS = { fage: { section: "红旗大街发哥", out: "skills/fage-skill/persona/score.json" } };
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const src = arg("src") || "fage";
const cfg = SRCS[src];
if (!cfg) { console.error(`未知 --src ${src}(可选: ${Object.keys(SRCS).join("/")})`); process.exit(1); }

const RE = /【核销 T\+1】([^·]*)·\s*(.*)/;
const num = (s, re) => { const m = s.match(re); return m ? +m[1] : 0; };
const days = [];
for (const q of fs.readdirSync("md").filter((d) => /^\d{4}S\d$/.test(d))) {
    for (const f of fs.readdirSync(path.join("md", q)).filter((f) => f.endsWith(".md")).sort()) {
        const text = fs.readFileSync(path.join("md", q, f), "utf8");
        // 只取目标小节内的核销行(防串节)
        const hi = text.indexOf(`#### ${cfg.section}`);
        if (hi === -1) continue;
        const rest = text.slice(hi);
        const endM = rest.slice(10).match(/^#{2,4} /m);
        const sec = endM ? rest.slice(0, 10 + endM.index) : rest;
        const m = sec.match(RE);
        if (m) days.push({ date: f.slice(0, 10), hit: num(m[1], /(?<!半)命中(\d+)/), half: num(m[1], /半命中(\d+)/), miss: num(m[1], /打脸(\d+)/), na: num(m[1], /不可证(\d+)/), note: m[2].trim() });
    }
}
if (!days.length) { console.error("未找到任何核销行"); process.exit(3); }

const agg = (list) => {
    const s = list.reduce((a, d) => ({ hit: a.hit + d.hit, half: a.half + d.half, miss: a.miss + d.miss, na: a.na + d.na }),
        { hit: 0, half: 0, miss: 0, na: 0 });
    const decidable = s.hit + s.half + s.miss;
    return {
        days: list.length, ...s, decidable,
        pureHitRate: decidable ? +(s.hit / decidable).toFixed(3) : null,
        halfHitRate: decidable ? +((s.hit + 0.5 * s.half) / decidable).toFixed(3) : null,
        naRate: (decidable + s.na) ? +(s.na / (decidable + s.na)).toFixed(3) : null,
    };
};
const score = {
    src, section: cfg.section, generatedAt: new Date().toISOString(),
    formula: "纯命中率=命中/(命中+半命中+打脸); 含半=(命中+0.5*半命中)/可判定; 不可证不计入",
    all: agg(days), last20: agg(days.slice(-20)),
    daily: days,
};
fs.mkdirSync(path.dirname(cfg.out), { recursive: true });
fs.writeFileSync(cfg.out, JSON.stringify(score, null, 1));
console.log(`记分卡 ${src}: 全量 ${score.all.days}天 纯命中 ${score.all.pureHitRate} 含半 ${score.all.halfHitRate} | 近20日 纯命中 ${score.last20.pureHitRate} 含半 ${score.last20.halfHitRate}`);
console.log(`JSON:${JSON.stringify({ out: cfg.out, days: days.length })}`);
