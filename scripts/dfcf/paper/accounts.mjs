// accounts.mjs — paper A 线账户元数据唯一真源(2026-10-11 从 report.mjs 抽出, report/daily_digest 共用)
// 固定顺序=固定颜色槽(颜色跟着实体走, 不随排名变): 槽 1-8 实线, 9-14 同色序虚线; 对照组=黑点线
export const ACCOUNTS = [
    ["A-taoge", "桃哥", "UP"], ["A-qushitiange", "趋势天哥", "UP"], ["A-lubenyuan", "卢本圆", "UP"],
    ["A-cb", "不吃土豆0(转债)", "导师"], ["A-liuyiqing", "刘忆青", "导师"], ["A-lianghuaxiaohao", "量化小号", "导师"],
    ["A-a658", "A658", "导师"], ["A-bianbenling", "边学本领", "导师"], ["A-xingjianye", "星见野", "导师"],
    ["A-daxingdaxingdadangxing", "大兴大A", "导师"], ["A-gaogailvfuli", "高概率复利", "导师"], ["A-xuanqiucaijing", "宣秋财经", "导师"],
    ["A-stzhilang", "ST之狼", "导师"], ["A-chong5000w", "冲5000w", "导师"],
    ["A-control", "对照组", "对照"],
];
export const TABLE_ONLY = [["B-taoge", "桃哥·人工", "B线"], ["B-cb", "土豆·人工", "B线"]];
export const NAME = Object.fromEntries([...ACCOUNTS, ...TABLE_ONLY].map(([s, n]) => [s, n]));
export const INIT = 100000;
