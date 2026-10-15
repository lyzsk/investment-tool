// layer_c_parse.mjs — tzzb C 层: 账本页渲染后文字 → 与 A 层同名字段的最小集(10/15 建, TODO A11)
// 输入=cdp_passive.htmlToText 的纯文本(每个块级元素一行)。页面结构(10/15 01:3x 刘忆青实测):
//   成绩上报时间 2026.10.14 14:58 / 本期比赛 +426.46% / 当日盈亏 +0.57% / 日历: "2026年10月" + 日一二三四五六 + [日号, (+x.xx% | 休 | 节日名 | 今 | -)]…
//   当日收益率：+0.57% / 当日持仓 (2026年10月14日) 表头 股票名称 操作 当日盈亏率 个股仓位 + 行[名, 代码, 操作, 盈亏率, 仓位]
//   操作记录 交易记录 表头 股票名称 操作 成交价 交易日期 + 行[名, 代码, 操作, 价, yy/mm/dd]
// 输出: { reportTime, totalRate, todayRate, daily:[{date:"yyyyMMdd", daily_rate}], positionDate, positions:[{code,name,op_text,rate,position_percent}],
//         trades:[{stock_code,stock_name,op_text,trans_price,trans_date}] }   (rate/percent 为小数, 与 A 层 profit 字段同口径)
const pct = (s) => +(+String(s).replace(/[%+]/g, "") / 100).toFixed(6);
const isPct = (s) => /^[+-]?\d+(\.\d+)?%$/.test(s);

export function parseLayerC(text) {
    const L = text.split("\n").map((x) => x.trim()).filter(Boolean);
    const out = { reportTime: null, totalRate: null, todayRate: null, daily: [], positionDate: null, positions: [], trades: [] };
    const at = (re, from = 0) => { for (let i = from; i < L.length; i++) if (re.test(L[i])) return i; return -1; };
    const rt = L.find((x) => /^成绩上报时间/.test(x));
    if (rt) out.reportTime = rt.replace(/^成绩上报时间\s*/, "");
    let i = at(/^本期比赛$/); if (i > -1 && isPct(L[i + 1])) out.totalRate = pct(L[i + 1]);
    const tr = L.find((x) => /^当日收益率[：:]/.test(x));
    if (tr) out.todayRate = pct(tr.split(/[：:]/)[1]);
    // 日历
    const mi = at(/^(\d{4})年(\d{1,2})月$/);
    if (mi > -1) {
        const [, y, m] = L[mi].match(/^(\d{4})年(\d{1,2})月$/);
        let year = +y, mon = +m;
        let j = mi + 1;
        while (j < L.length && /^[日一二三四五六]$/.test(L[j])) j++;
        // 首行可能带上月尾巴(如 27 28 29 30 01): 见到 "01" 之前的日号属于上个月
        let seenFirst = false, curY = mon === 1 ? year - 1 : year, curM = mon === 1 ? 12 : mon - 1;
        for (; j < L.length && !/^当日收益率/.test(L[j]); j++) {
            if (!/^\d{1,2}$/.test(L[j])) continue;
            const day = +L[j];
            if (day === 1 && !seenFirst) { seenFirst = true; curY = year; curM = mon; }
            if (!seenFirst && day < 20) { seenFirst = true; curY = year; curM = mon; }   // 当月从非 1 号开始显示(无上月尾巴)
            const nx = L[j + 1] || "";
            if (isPct(nx)) out.daily.push({ date: `${curY}${String(curM).padStart(2, "0")}${String(day).padStart(2, "0")}`, daily_rate: pct(nx) });
        }
    }
    // 当日持仓
    const pi = at(/^当日持仓$/);
    if (pi > -1) {
        const dm = (L[pi + 1] || "").match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
        if (dm) out.positionDate = `${dm[1]}${dm[2].padStart(2, "0")}${dm[3].padStart(2, "0")}`;
        const hs = at(/^个股仓位$/, pi), end = at(/^操作记录$/, pi);
        for (let k = hs + 1; hs > -1 && k < (end > -1 ? end : L.length); k++) {
            if (!/^\d{6}$/.test(L[k])) continue;
            const name = L[k - 1], rest = L.slice(k + 1, k + 4);
            const pcts = rest.filter(isPct);
            out.positions.push({ code: L[k], name, op_text: rest.find((x) => !isPct(x) && !/^\d{6}$/.test(x)) || "", rate: pcts[0] != null ? pct(pcts[0]) : null,
                position_percent: pcts[1] != null ? pct(pcts[1]) : null });
        }
    }
    // 交易记录
    const ti = at(/^交易记录$/);
    if (ti > -1) {
        const hs = at(/^交易日期$/, ti), end = at(/^已加载全部内容$|^加载更多/, ti);
        for (let k = hs + 1; hs > -1 && k < (end > -1 ? end : L.length); k++) {
            if (!/^\d{6}$/.test(L[k])) continue;
            const [op, price, date] = L.slice(k + 1, k + 4);
            const dm = (date || "").match(/^(\d{2})\/(\d{2})\/(\d{2})$/);
            out.trades.push({ stock_code: L[k], stock_name: L[k - 1], op_text: op || "", trans_price: /^\d+(\.\d+)?$/.test(price || "") ? price : null,
                trans_date: dm ? `20${dm[1]}-${dm[2]}-${dm[3]}` : date || null });
        }
    }
    return out;
}
