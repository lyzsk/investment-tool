// reset_books.mjs — A 线发令枪重置(2026-10-08 盘前用, 10/7 用户拍板"统一")
// 语义: A 线四本(taoge/cb/qushitiange/lubenyuan)重置为 10 万初始(nav 历史清零, 9/28-30 热身作废);
//      nav_<book>.csv 同步删除 9/28-30 行; B/C 线一律不动。
// 幂等: 已是初始态再跑=无操作。用法: node scripts/dfcf/paper/reset_books.mjs [--dry]
import fs from "fs";
import path from "path";

const DRY = process.argv.includes("--dry");
const DIR = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const BOOKS = ["A-taoge", "A-cb", "A-qushitiange", "A-lubenyuan"];
const DEAD_DATES = new Set(["2026-09-28", "2026-09-29", "2026-09-30"]);

for (const b of BOOKS) {
    const f = path.join(DIR, "books", `${b}.json`);
    if (!fs.existsSync(f)) { console.log(`${b}: 无 book, 跳过(matcher --init 会建)`); continue; }
    const book = JSON.parse(fs.readFileSync(f, "utf8"));
    const navHist = book.nav?.filter?.(n => n.date && !DEAD_DATES.has(n.date)) || [];
    const before = book.nav?.length || 0;
    book.cash = 100000;
    book.positions = {};   // 10/8 修: 必须是 dict 不是 list(驱动器 book_nav 用 .values())
    book.orders = [];
    book.trades = [];
    book.nav = navHist;
    console.log(`${b}: nav ${before}→${navHist.length} 行(删 9/28-30), 现金/持仓/挂单/成交 清零 → 10 万发令枪`);
    if (!DRY) fs.writeFileSync(f, JSON.stringify(book, null, 1));
    const csv = path.join(DIR, "nav", `nav_${b}.csv`);   // 10/8 起 nav csv 在 nav/ 子目录
    if (fs.existsSync(csv)) {
        const lines = fs.readFileSync(csv, "utf8").split("\n");
        const kept = lines.filter(l => !DEAD_DATES.has(l.slice(0, 10)));
        if (kept.length !== lines.length) {
            console.log(`  nav_${b}.csv: ${lines.length - kept.length} 行删除`);
            if (!DRY) fs.writeFileSync(csv, kept.join("\n"));
        }
    }
}
console.log(DRY ? "[dry] 完" : "A 线发令枪就位(10 万 × 4)");
