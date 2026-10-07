// client.mjs — 行情数据源统一客户端(2026-10-07 建, §F.9 数据源治理落点)
// 定位: 只做三件事——①共享 fetchBuf(IPv4 强制+UA+超时, scan 实证 undici v6 死路由)
//   ②健康台账 sources_health.json(谁/何时/成败, 跨日累计=数据源巡检唯一事实)
//   ③logHealth() 供各脚本在成功/失败/降级分支各记一行。
// 立法(10/5): 任何行情拉取禁单源直连; 本模块不负责各家的解析/降级链(仍归各脚本, 高内聚),
//   只收敛"请求壳+健康记录"——大重构禁止临阵做(10/8 首跑前只做增量接线)。
// 台账: scripts/quotes/sources_health.json {events:[{ts,script,board,src,ok,err}]}, 环形上限 2000 条。
import fs from 'fs';
import path from 'path';
import http from 'http';
import https from 'https';
import { fileURLToPath } from 'url';

const HEALTH = path.join(path.dirname(fileURLToPath(import.meta.url)), 'sources_health.json');
const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' };

export function fetchBuf(url, headers = {}, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, { family: 4, headers: { ...UA, ...headers }, timeout: timeoutMs }, res => {
      if (res.statusCode >= 400) { res.resume(); return reject(new Error('HTTP ' + res.statusCode)); }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    });
    req.on('timeout', () => req.destroy(new Error('timeout>' + timeoutMs + 'ms')));
    req.on('error', reject);
  });
}

export async function fetchJson(url, headers = {}) {
  return JSON.parse((await fetchBuf(url, headers)).toString('utf8'));
}

export function logHealth(script, board, src, ok, err = null) {
  try {
    let j = { events: [] };
    try { j = JSON.parse(fs.readFileSync(HEALTH, 'utf8')); } catch { /* 首次 */ }
    j.events.push({ ts: new Date().toISOString(), script, board, src, ok, err: err ? String(err).slice(0, 120) : null });
    if (j.events.length > 2000) j.events = j.events.slice(-2000);  // 环形, 防无限膨胀
    fs.writeFileSync(HEALTH, JSON.stringify(j, null, 1), 'utf8');
  } catch { /* 台账失败绝不伤主管线 */ }
}

// 降级数据源(§5.5 对策, 10/7 建): 今日产物缺失时读最近一份历史 scan 产物续链。
// parentDir=run 目录的父级(内含 live-YYYYMMDD 等子目录); skipName=今日目录名。返回 {md, json, from} 或 null。
export function latestPriorScan(parentDir, skipName) {
  try {
    const dirs = fs.readdirSync(parentDir).filter(d => d !== skipName).sort().reverse();
    for (const d of dirs) {
      const f = path.join(parentDir, d, 'scan.json');
      if (fs.existsSync(f)) {
        const json = JSON.parse(fs.readFileSync(f, 'utf8'));
        const mdF = path.join(parentDir, d, 'scan.md');
        const md = fs.existsSync(mdF) ? fs.readFileSync(mdF, 'utf8') : null;
        return { md, json, from: d };
      }
    }
  } catch { /* 无历史=正常返回 null */ }
  return null;
}
