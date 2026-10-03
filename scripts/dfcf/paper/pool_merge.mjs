// pool_merge.mjs — 04 扩池提案机械落 pools.json(2026-10-04 用户拍板: 自动落, 零 token)
// 输入: 提案 JSON 文件 [{"direction":"...","names":["票名",...]}](链 04 contract pool_proposals, 驱动器 v04 已校验结构)
// 动作: 票名→代码(smartbox.gtimg.cn 解析, 精确名匹配+GP 类型) → merge 进 pools.json(去重 by 名称, 新方向自动建组)
// 出口: 0=ok(含零提案) 1=用法/文件错; 单票解析失败不致命(记 unresolved 继续, 诚实列进输出供人工补)
// 用法: node scripts/dfcf/paper/pool_merge.mjs --file <proposals.json>
import fs from "node:fs";
import path from "path";

const POOLS = path.resolve("skills/taoge-skill/persona/pools.json");
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : null; };
const file = arg("file");
if (!file) { console.error("用法: --file <proposals.json>"); process.exit(1); }
const proposals = JSON.parse(fs.readFileSync(file, "utf8"));
const pools = JSON.parse(fs.readFileSync(POOLS, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function resolveCode(name) {  // smartbox: "sh~688185~康希诺~kxn~GP-A-KCB^hk~..." 精确名+GP 类型
    const r = await fetch(`https://smartbox.gtimg.cn/s3/?v=2&q=${encodeURIComponent(name)}&t=all`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const t = new TextDecoder("gbk").decode(await r.arrayBuffer());
    const body = (t.match(/="([\s\S]*)"/) || [, ""])[1]
        .replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));  // 名字段是 \uXXXX 转义, 先还原再比
    for (const rec of body.split("^")) {
        const f = rec.split("~");
        if (f.length >= 5 && f[2] === name && f[4].startsWith("GP")) return f[1];
    }
    return null;
}

const added = [], unresolved = [], dup = [];
for (const p of proposals) {
    const dir = p.direction, names = p.names || [];
    if (!pools.directions[dir]) pools.directions[dir] = { 建立: new Date().toISOString().slice(0, 10), 依据: "04 扩池提案自动落(10/4 用户拍板)", stocks: [] };
    const have = new Set(pools.directions[dir].stocks.map((s) => s.name));
    for (const n of names) {
        if (have.has(n)) { dup.push(`${dir}/${n}`); continue; }
        let code = null;
        try { code = await resolveCode(n); } catch { }
        if (!code) { unresolved.push(`${dir}/${n}`); continue; }
        pools.directions[dir].stocks.push({ code, name: n, 来源: `04扩池提案 ${new Date().toISOString().slice(0, 10)}` });
        added.push(`${dir}/${n}(${code})`);
        await sleep(300 + Math.random() * 400);  // 防封抖动
    }
}
pools._meta.最近自动落 = `${new Date().toISOString().slice(0, 10)}: +${added.length} 票, 解析失败 ${unresolved.length}, 重复跳过 ${dup.length}`;
fs.writeFileSync(POOLS, JSON.stringify(pools, null, 2), "utf8");
console.log(`JSON:${JSON.stringify({ added, unresolved, dup })}`);
