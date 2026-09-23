// dblog.mjs — db_bound JSONL 写入(列名=未来DB表结构) + 防作伪哈希链
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
export const DB_DIR = path.join(ROOT, 'db_bound');

// 追加一行到 db_bound/<table>.jsonl (keys 即列名, 调用方负责与表结构对齐)
export function dbRow(table, obj) {
  fs.mkdirSync(DB_DIR, { recursive: true });
  fs.appendFileSync(path.join(DB_DIR, table + '.jsonl'), JSON.stringify(obj) + '\n');
}

// 哈希链: 每个决策文件写完后立即上链, 之后任何改动都会断链
export function hashchain(file) {
  const chainFile = path.join(ROOT, 'hashchain.log');
  let prev = 'GENESIS';
  if (fs.existsSync(chainFile)) {
    const lines = fs.readFileSync(chainFile, 'utf8').trim().split('\n').filter(Boolean);
    if (lines.length) prev = JSON.parse(lines[lines.length - 1]).hash;
  }
  const content = fs.readFileSync(file);
  const hash = crypto.createHash('sha256').update(prev).update(content).digest('hex');
  fs.appendFileSync(chainFile, JSON.stringify({
    hash, prev, file: path.basename(file), at: new Date().toISOString(),
  }) + '\n');
  return hash;
}

// 数据洞: 宁可记洞不编造
export function hole(what, detail) {
  fs.appendFileSync(path.join(ROOT, 'holes.log'),
    `${new Date().toISOString()}\t${what}\t${String(detail).replaceAll('\n', ' ').slice(0, 300)}\n`);
}

export function wakeLog(entry) {
  fs.appendFileSync(path.join(ROOT, 'wake_requests.jsonl'), JSON.stringify({
    at: new Date().toISOString(), ...entry,
  }) + '\n');
}
