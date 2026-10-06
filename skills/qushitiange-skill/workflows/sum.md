# qushitiange-skill · sum 工作流（视频产物合成）

> 路由来源: SKILL.md。与 taoge sum 共用同一条上游状态机(`bilibili_video` 表按 `author_mid` 区分)和同一个 controller。

## 纪律(继承 taoge sum 全部, 编号对应)

1. AI 写库只走 controller: `POST /api/bilibili/video/markSummarized`; **本工作流只处理 authorMid==1372241958 的行**
2. 幻觉防控: 只写产物文件里有的信息, 缺就标注, 绝不脑补
3. 股票代码以 OCR/多帧投票为准, 对不上标 `[?]`
4. 不改/不删 downloads 与 results 任何文件
5. `#### 趋势天哥` 整小节覆盖(幂等), 只可能是本工作流产出
6. 格式机械可验: 小节内禁 `#####` 子标题:
   `awk '/^#### 趋势天哥/{f=1;next} /^#{2,4} /{if(f)exit} f' <md> | grep -c '^##### '` 应为 0

## 步骤

1. 发现: `curl -s localhost:8888/api/bilibili/video/pendingSummary`, **过滤 authorMid==1372241958**; 空列表=没活结束
2. 产物定位: `results/bilibili/1372241958/<发布日 yyyy.MM.dd>/<bvid>.{txt,vision.json}`; 三态判定同 taoge sum(全齐/仅txt/全缺不合成)
3. 合成挂载: `md/<year>S<quarter>/<发布日>.md` → `## 复盘` → `### bilibili` → `#### 趋势天哥`(10/5 模板已加骨架, migrate 已补历史)
4. 小节结构(**冷启动简化版, 样本≥10 天后按实际风格修订**——他是趋势视角, 预期重心=方向/趋势票/仓位节奏, 但以产物实证为准不许预设):
```markdown
#### 趋势天哥

**[视频标题](https://www.bilibili.com/video/<bvid>)** · HH:MM 发布 · N 分钟 ·（语音转写）

> 逐字稿引用块(按自然段, 原声照留)

- **大盘/趋势定调**: 指数趋势/量能/他的一句话定调(画面确认的数据标注)
- **今日操作**(如有): 买/卖/持有 逐条带价位, 画面确认为准
- **提及个股**: 名称(代码) · 态度 — 依据一句话; 代码以 OCR/多帧投票为准
- **画面增量(口述未提)**: 注意力榜/持仓高亮等视觉证据; 无则写"无"不许省略
- **规则沉淀**: 可迁移规则, 每条带当天证据; 单样本标"(样本1, 待验证)"
```
5. 推进: 只推合成成功的, curl markSummarized(bvid 数组); 回填日期无表行则跳过(文件驱动, 同 taoge sum §4)
