---
name: check-cls-md
description: "检查/修正某日 md 里 cls 图 OCR 自动填充的四小节(午评/午间涨停分析/收评/涨停分析)。用户下班说'检查今天md'时用。Java 定时链已自动下载+OCR+填充, 本 skill 做 AI 复核: 直接看图 vs md 小节全量比对, 错字直改, 数据以图为准覆盖, PARSE_FAIL/缺图列清单。"
---

# cls OCR 填充检查 (investment-tool, 2026-09-25 用户定)

> 本文件是**主副本**(随 git 走, 新机器/他人可读)。`.claude/skills/check-cls-md/SKILL.md` 是 Claude Code 运行时加载的镜像, 改这份后同步过去: `cp skills/check-cls-md/SKILL.md .claude/skills/check-cls-md/SKILL.md`

前置：Java 定时链(ClsTelegraphServiceImpl, TODO 2.7)已自动完成 下载→`scripts/cls/cls_image_ocr.py` OCR→replaceSection 覆盖填充。裸 OCR 有语义级错字(AI→Al、引号缺半)和旧版式 PARSE_FAIL 两类短板，本 skill 补这一刀。

## 输入

- 日期(默认今天)。cls 图目录 `downloads/cls/yyyy.MM.dd/`(点分隔), md 在 `md/<季度>/yyyy-MM-dd.md`(横线, 季度=(月-1)/3+1 → `2026S3`)

## 检查流程

1. `ls downloads/cls/<yyyy.MM.dd>/` 列图, 按文件名 `cls_{wp,wjzt,sp,zt}_时间戳_N.{jpg,png}` 分组:
   - 同一 suffix 多时间戳组 = 电报重发, 只查最新组
   - wjzt/zt 可多张(N 升序), wp/sp 只应一张; **张数与 md 小节内容完整性感知**(zt 两张图只填了一半=缺张, 报用户)
2. 读 md 对应小节(suffix→小节: wp→`## 午评`, wjzt→`## 午间涨停分析`, sp→`## 收评`, zt→`## 涨停分析`):
   - **小节空/缺 → 直接补齐(2026-09-30 用户定: 未填项直接 append, 不再只报告)**:
     a. 有图但 PARSE_FAIL(Java 日志或手动重跑 `scripts/venv/Scripts/python.exe scripts/cls/cls_image_ocr.py <图> --type <suffix>` 确认) → **切片多模态补填**: 长图按高 ~1700px/重叠 120px 切片(scripts/venv 的 PIL), 逐片 Read 直读转 md 表格(格式对齐上一交易日同小节), 小节开头标注 `(OCR PARSE_FAIL, 多模态补填 <日期>)`
     b. 缺图 → **先查 DB 当天带图电报**(`cls_telegraph`, pymysql host=localhost user=root password=root db=investment_tool): 标题分类可能漏(实证 2026-09-30: 收评电报 12905 本身无图, 15:47 补充稿 12907 带图但标题不含"收评"未被 `isShouPingItem` 识别)——找到就下载(`Referer: https://www.cls.cn`)按 a 补录, 注明来源电报 id; 真无图源才在报告里注明缺源
     c. 补齐后**仍要在报告里列出补了哪几节**, 让用户可复核
3. **逐张 Read 图(多模态直读) vs md 小节比对**: 四小节一律全检, 不搞"有警告才复核"——wp/sp 核 13 档数字+概况行, zt/wjzt 核每行 名称/6位代码/板数/涨跌幅/涨停时间/上涨逻辑+主题归因段文字
4. 修正口径(发现就直接改, 填充覆盖):
   - **错字级**(引号半缺、AI→Al、IonQ→lonQ 类): 直接 Edit 修
   - **数据级**(数字/代码/涨跌幅与图不符): 以图为准直接 Edit 覆盖
   - 图本身糊到我也读不准的格: 标 `(待核)` 并列出, 不猜
5. 输出报告: 改了哪几处(错字/数据分开列)、PARSE_FAIL/缺图/缺张清单、我不确定的格子

## 边界

- 只动四小节; md 其他部分(复盘/桃哥/加红电报)一个字不动
- 6-8 月旧版式图会 PARSE_FAIL(解析器按 9 月版式标定)——遇到就报告, 回填旧版式兼容是 TODO 2.7 遗留项, 不在本 skill 里现场修解析器
