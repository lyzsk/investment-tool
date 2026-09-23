// wechat_sync.mjs — 每日微信对话同步: hermes agent.log → wechat/<date>.md
// 目的(2026-09-22 用户指令): 用户盘中通过微信clawbot和hermes(kimi)的对话=用户盘中所想,
// 每晚回家同步给两个交易agent(taoge-paper/k3-inv), 场景复盘升级为"用户 vs Claude vs 桃哥"三方对照。
// 用法: node wechat_sync.mjs [--date 20260922]   缺省=今天
// 闭环: 日志缺失/无消息也产出文件(注明原因), 不抛异常给调用方。
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
let DATE = args.includes('--date') ? args[args.indexOf('--date') + 1] : null;
if (!DATE) {
  const d = new Date();
  DATE = String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
}
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const LOG = (cfg.inbox || {}).log || 'C:/Users/admin/AppData/Local/hermes/logs/agent.log';
const OUT_DIR = path.join(ROOT, 'wechat');
fs.mkdirSync(OUT_DIR, { recursive: true });

const dash = `${DATE.slice(0, 4)}-${DATE.slice(4, 6)}-${DATE.slice(6, 8)}`;
const lines = [`# 微信对话同步 ${dash} (来源: hermes agent.log, 仅入站=用户本人发言)`, ''];

if (!fs.existsSync(LOG)) {
  lines.push(`(hermes日志不存在: ${LOG} — hermes-agent未运行或路径变了)`);
} else {
  const re = new RegExp(`^(${dash} \\d{2}:\\d{2}:\\d{2}),\\d+ INFO gateway\\.run: inbound message: platform=weixin .* msg='(.*)' reply_to_id=`);
  const msgs = [];
  for (const line of fs.readFileSync(LOG, 'utf8').split('\n')) {
    const m = line.match(re);
    if (!m) continue;
    const msg = m[2].trim();
    if (/^\[(IMPORTANT|SYSTEM|note)/i.test(msg)) continue;   // hermes内部系统通知误入inbound流
    msgs.push({ t: m[1].slice(11), msg: msg || '(非文本消息: 图片/附件)' });
  }
  if (!msgs.length) lines.push('(当日无入站微信 — 用户今天没和bot说话, 或日志已滚动覆盖)');
  for (const m of msgs) lines.push(`- [${m.t}] ${m.msg}`, '');
  lines.push(`---`, `共 ${msgs.length} 条。注意: ①kimi的回复不在此日志(agent.log只记response字数) ②hermes日志对长消息截断~200字, 被截的消息找微信原记录 ③图片内容在hermes会话侧, 需要时让用户贴给Claude。`);
}

fs.writeFileSync(path.join(OUT_DIR, DATE + '.md'), lines.join('\n'));
console.log(`wechat/${DATE}.md: ${lines.length > 4 ? lines.filter(l => l.startsWith('- [')).length : 0} 条入站消息`);
