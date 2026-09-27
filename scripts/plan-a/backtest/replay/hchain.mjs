// hchain.mjs — replay 运行目录内的防作伪哈希链 + 数据洞记录(每跑一次一个独立 run 目录, 链独立)
// 模式照搬 scripts/taoge-paper/dblog.mjs, 但不共用文件: 回测链与模拟盘链物理隔离, 互不污染。
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

// 每个 run 目录一条链: 决策文件落盘后立刻上链, 之后任何改动都会断链
export function makeChain(runDir) {
  const chainFile = path.join(runDir, 'hashchain.log');
  return function chain(file) {
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
  };
}

// 数据洞: 宁可记洞不编造(停牌/无数据/解析歧义/规则不可机械化 全部记洞)
export function makeHole(runDir) {
  const f = path.join(runDir, 'holes.log');
  return function hole(what, detail) {
    fs.mkdirSync(runDir, { recursive: true });
    fs.appendFileSync(f,
      `${new Date().toISOString()}\t${what}\t${String(detail).replaceAll('\n', ' ').slice(0, 300)}\n`);
  };
}
