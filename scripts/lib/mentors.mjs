// mentors.mjs — 导师登记表读取口(10/17 二B-4; py 同口径 = mentors.py, 字段/顺序说明见那边文件头)
// 登记表 = scripts/tzzb/tzzb_ledgers.json(tzzb, id=ledger) + scripts/tzzb/mentor_registry_extra.json(UP/对照); 只有带 book 的条目算链
// 用法: import * as M from "../../lib/mentors.mjs"; M.ids("tzzb"); M.book("buchitudou0") → "A-cb"; 自测 node scripts/lib/mentors.mjs --selftest
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const T = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "tzzb");
const ORDER = { UP: 0, tzzb: 1, 对照: 2 };
const rd = (f) => JSON.parse(fs.readFileSync(path.join(T, f), "utf8"));
export const all = () => [...rd("mentor_registry_extra.json").entries,
    ...rd("tzzb_ledgers.json").filter((e) => e.book).map((e) => ({ ...e, id: e.ledger }))].sort((a, b) => ORDER[a.type] - ORDER[b.type]);
export const ids = (...types) => all().filter((e) => !types.length || types.includes(e.type)).map((e) => e.id);
export const get = (id) => all().find((e) => e.id === id);
export const book = (id) => get(id).book;
export const byBook = (bk) => all().find((e) => e.book === bk)?.id;
export const head = (id) => get(id).short.split("(")[0];

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url) && process.argv.includes("--selftest")) {
    const E = all(), ok = (c, m) => { if (!c) { console.error("FAIL: " + m); process.exit(1); } };
    ok(new Set(E.map((e) => e.id)).size === E.length && new Set(E.map((e) => e.book)).size === E.length, "id/book 重复");
    ok(ids("UP").join() === "taoge,qushitiange,lubenyuan" && ids("对照").join() === "control", "UP/对照");
    ok(book("buchitudou0") === "A-cb" && byBook("A-cb") === "buchitudou0" && head("lianghuaxiaohao") === "量化实验", "book/head");
    const { execFileSync } = await import("child_process");   // 与 py 版逐项一致
    const py = execFileSync(process.env.PY || "python", ["-X", "utf8", "-c", "import sys,json;sys.path.insert(0,sys.argv[1]);import mentors;print(json.dumps(mentors.all(),ensure_ascii=False))", path.join(T, "..", "lib")], { windowsHide: true }).toString();
    ok(JSON.stringify(JSON.parse(py)) === JSON.stringify(E), "py/mjs 读出不一致");
    console.log(`mentors.mjs selftest OK: ${E.length} 条链, 与 mentors.py 逐项一致`);
}
