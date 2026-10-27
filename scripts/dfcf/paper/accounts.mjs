// accounts.mjs — paper A 线账户元数据唯一真源(2026-10-11 从 report.mjs 抽出, report/daily_digest 共用)
// 固定顺序=固定颜色槽(颜色跟着实体走, 不随排名变): 槽 1-8 实线, 9-14 同色序虚线; 对照组=黑点线
// 10/17 二B-4: 导师链(UP/tzzb 导师/对照组)读导师登记表(scripts/lib/mentors.mjs, 顺序=槽位序), 这里只留混合账本
import * as MENTORS from "../../lib/mentors.mjs";
export const ACCOUNTS = [
    ...MENTORS.all().map((e) => [e.book, e.display, e.type === "tzzb" ? "导师" : e.type]),   // 10/18 晚 t_bot.py   // 10/16 新增(槽 18-20, mix_plans.py)
];
// 10/22 凌晨: books_ext/accounts.json(books_ext.py 导出: 新 paper 模拟账 S-<导师> / 统计基线 BL- / BLT-), 只进报告, 不进 matcher / 日报 ACTIVE
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
try {
    const f = path.join(path.dirname(fileURLToPath(import.meta.url)), "books_ext", "accounts.json");
    for (const a of JSON.parse(fs.readFileSync(f, "utf8"))) if (!ACCOUNTS.some(([s]) => s === a[0])) ACCOUNTS.push(a);
} catch { /* 没导出过 = 只有原账户 */ }
export const NAME = Object.fromEntries(ACCOUNTS.map(([s, n]) => [s, n]));
// 10/19: 在跑的账户(去掉退出 paper 的导师, mentors.mjs 与 py 版 active_ids 对等); 日报 / 真人对照用这个, 报告用 ACCOUNTS + "只看在跑"按钮
export const ACTIVE = ACCOUNTS.filter(([src]) => MENTORS.isActiveBook(src));   // 10/19: B 线(人工账本)永久取消, 账本与代码已删
export const INIT = 100000;
