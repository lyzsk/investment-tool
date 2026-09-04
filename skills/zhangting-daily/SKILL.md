---
name: zhangting-daily
description: "Use when 用户要求处理当天涨停分析或ST股OCR或收盘复盘持仓。涨停图→千问→md；ST股OCR；复盘持仓记md。"
---

# 涨停分析日报流程 (investment-tool)

用户在交易日（周一至周五）通过微信触发。两条主线可独立或先后执行。

## 关键路径与日期规则

| 项 | 路径/格式 |
|---|---|
| cls 图片目录 | `C:\Users\admin\dev\investment-tool\downloads\cls\yyyy.MM.dd\`（点分隔，如 `2026.08.24`） |
| 涨停图文件名 | `cls_zt_yyyymmdd_HHMMSS_N.jpg`（N=1,2,... 可能多张；只取 `cls_zt_` 前缀的，忽略 cls_sp/cls_wjzt/cls_wp） |
| md 目标文件 | `C:\Users\admin\dev\investment-tool\stocks\<季度>\<yyyy-MM-dd>.md`（横线分隔，如 `2026S3\2026-08-24.md`） |
| 季度文件夹 | `2026S1`=1-3月, `S2`=4-6月, `S3`=7-9月, `S4`=10-12月 |
| 微信图片缓存 | `%LOCALAPPDATA%\hermes\cache\images\`（网关自动解密缓存；旧版在 `hermes\image_cache\`） |
| 后端 API | `http://localhost:8888`（Spring Boot，确认 LISTENING 再调） |
| 数据库 | MySQL `localhost:3306/investment_tool`，user/pass = root/root |

md 文件结构（参照 stocks\2026S3\2026-08-21.md）：`## 涨停分析` 下是若干 `### <板块>`（归因+表格），最后是 `### ST 股`（编号列表）。当天的 md 模板通常已存在（如 2026-08-24.md），`## 涨停分析` 下为空。

## 主线 A：涨停分析（cls_zt 图片 → 千问 → md）

1. `ls "C:/Users/admin/dev/investment-tool/downloads/cls/<yyyy.MM.dd>/"` 确认当天文件夹存在，列出所有 `cls_zt_*.jpg`。文件夹不存在就告诉用户还没下载。
2. 用 computer_use 驱动这台 PC 的 Chrome（千问标签页，bookmark 栏有"千问"，页面标题"千问-阿里 AI 助手"；无 Chrome 窗口时 `cmd.exe /c start chrome https://www.qianwen.com`）：
   - **Chrome 在 PC1 常驻不关，永远直接访问已有标签页**（2026-08-27 用户明确）：list_windows 找不到 Chrome 窗口 = 最小化/托盘，先还原窗口，**禁止重启/重开 Chrome、禁止新开千问 tab**。已有「千问」标签用 Ctrl+数字 切换直达
   - **文件管理器同理**：需要展示 cls 文件夹时，先看是否已有该路径的 Explorer 窗口（标题含 `yyyy.MM.dd`），有就复用激活，没有再 `explorer.exe <路径>` 新开
   - capture(app='Chrome') 拿 SOM 元素；输入框=Edit「向千问提问」
   - **上传图片首选剪贴板粘贴法（2026-08-25 验证，比附件按钮稳）**：`powershell.exe -STA -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; $img=[System.Drawing.Image]::FromFile('<图片全路径>'); [System.Windows.Forms.Clipboard]::SetImage($img)"` → 点输入框 → Ctrl+V（foreground）；多图逐张重复。附件按钮弹的原生文件对话框不进 AX 树、后台点击不触发，勿用
   - 在输入框输入 `生成md` → Enter 发送
   - 等 60-90s 回复完成
3. 取结果：**若回复是富文本表格（无代码块）**，追加发送「把上面的整理结果原样放到一个markdown代码块中输出，不要改动内容」→ 新回复出代码块（头行有 'markdown' 语言标签，其右侧第一个图标按钮=复制）→ 点复制 → **用 pyperclip 读剪贴板**（`uv run --with pyperclip python -c "import pyperclip;print(pyperclip.paste())"`；勿写 .ps1 再执行，易触发审批拦截）
4. 内容转换后写入：删千问标题行（它可能写错年份，如把2026写成2025）和 `---` 后的 branding；`## 板块` → `### 板块`；`**归因：**` → `归因：`；表格行间不得插空行（否则 md 表格断裂）；插入到 `## 涨停分析` 正下方、**`### ST 股` 之前**（ST 股永远是涨停分析最后一个小节）。
4. **必须做 Ctrl+S 格式化**（见下方"VS Code 格式化"节）。
5. 完成后向用户汇报：写入了哪些板块、股票总数。

## 主线 B：ST 股（微信图片 → OCR → md）

用户在微信里发 N 张 ST 股涨停截图。

1. 收图：网关会把图片缓存到 `%LOCALAPPDATA%\hermes\cache\images\img_*.jpg`。按修改时间取最新 N 张（N=用户本次发的数量），复制到 `C:\Users\admin\Downloads\st_ocr\` 专用目录（先清空，避免混入旧图）。**不需要**打开 PC 微信。
2. 上传+OCR（直接调 API，等价于用户的 Postman 三步；path 传 st_ocr 专用目录）：
   ```bash
   curl -s -X POST "http://localhost:8888/api/file/batch-upload-from-disk?category=ocr&path=C%3A%5CUsers%5Cadmin%5CDownloads%5Cst_ocr&extensions=jpg"
   curl -s -X POST http://localhost:8888/api/ocr/sync
   curl -s -X POST http://localhost:8888/api/ocr/process   # Tesseract OCR，每张可能数秒，超时给足
   ```
   返回 `{"code":"200","data":<数量>,"msg":"成功"}` 即正常。
3. 查询 OCR 结果（无需 DBeaver，用 uv 临时带 pymysql）：
   ```bash
   uv run --with pymysql python -c "
   import pymysql
   c=pymysql.connect(host='localhost',user='root',password='root',database='investment_tool',charset='utf8mb4')
   cur=c.cursor(); cur.execute('select processed_text from ocr_result order by id desc limit <N>')
   [print(r[0]) for r in cur.fetchall()]"
   ```
   `<N>` = 本次实际下载的图片数。确认结果的 create_time 是刚才（避免拿到旧数据）。
4. 把 N 条 processed_text 按 `1. ` `2. ` `3. ` 编号，追加到当天 md 的 `### ST 股` 小节下（若 `### ST 股` 不存在，在 `## 涨停分析` 内容末尾、 `## 涨停梯队` 之前新建）。原样粘贴 OCR 文本，不要擅自纠错（参照 2026-08-21.md 第 177-181 行的原始风格）。例外：**股票名称明显识别错时按代码校正并在括号注明**（如 2026-08-25 OCR 把"美芝"误识为"天之"，按 002856 校正）。
5. **必须做 Ctrl+S 格式化**。

## 主线 C：复盘持仓（收盘后记录持仓，按金额从大到小）

1. 获取持仓（优先顺序）：
   - 用户微信发持仓截图 → 主线 B 的 OCR 流程识别
   - 或 PC2 东财远程截屏（skill: pc2-remote-screen）：`ssh Administrator@100.111.59.0` 调 cua-driver get_window_state 截图 → RapidOCR（`uv run --with rapidocr-onnxruntime`，比后端 Tesseract 准得多，东财界面小字 Tesseract 是糊的）
   - 注意：东财「持仓」分组在自选股面板 ≠ 券商交易模块的持仓明细；精确金额需要用户打开 F12 交易端，否则按已知份额×现价估算并注明"约"
2. 收盘价：qt.gtimg.cn 实时接口（15:00 后=收盘价）。
3. 写入当天 md 的 `## 复盘` → `### 复盘持仓`，格式（参照 2026-08-25.md）：
   ```
   #### <名称> |
   ```
   **「|」后面留白，什么都不写**（用户明确要求 2026-08-25：收盘价/金额都不要填，留给他自己记）。**顺序 = 持仓金额从大到小**。
4. Ctrl+S 格式化。

## VS Code 格式化（Ctrl+S，用户明确要求，不可跳过）

**所有对 stocks/ 下 md 的操作结束后，最后一步必须是 Ctrl+S**——用户 VS Code 开了 format-on-save，会自动把表格对齐、中英文空格等排版规范化（2026-08-25 验证：千问粘贴的紧凑表格经 Ctrl+S 后自动变成对齐格式）。没有这一步，文件就是未排版状态。

用户 VS Code 开了 format-on-save，粘贴后必须保存一次让排版规范化：

1. 文件已用 write_file/patch 写好后，`code "C:\Users\admin\dev\investment-tool\stocks\<季度>\<date>.md"` 在已运行的 VS Code 里打开
2. computer_use capture(app='Code') → key ctrl+s（background 投递即可）
3. 等 2 秒，read_file 读回确认排版已格式化（表格对齐等变化）

## 验证清单

- [ ] cls 文件夹日期 = 当天，图片张数与预期一致
- [ ] 千问回复确实含 markdown 代码块（板块+表格结构）再复制
- [ ] md 里 `## 涨停分析` 下有新内容且无重复粘贴
- [ ] ST 股条数 = 微信图片数，编号连续
- [ ] Ctrl+S 后读回文件确认格式化生效
- [ ] 全程在微信里向用户简报进度（用户在微信端等结果）

## 坑

- **绝对不要关闭/重启用户的 Chrome（或任何用户正在用的应用）**（2026-08-27 用户严正要求）：不 taskkill、不点 X、不 restart。找不到窗口时先 list_windows 确认是否只是最小化/托盘；确需打开页面只用 `start chrome <url>` 追加 tab，自己新开的 tab 用完要关也先问用户。

- **浏览器断网先查 PAC，不是 ProxyEnable**（2026-08-24 实踩）：千问页面突然 ERR_CONNECTION_CLOSED 或弹 Privoxy 500，但 `curl` 直连 200 正常 → 本机 Shadowsocks 是 **PAC 模式**（`HKCU\...\Internet Settings` 的 `AutoConfigURL=http://127.0.0.1:1080/pac?...`，ProxyEnable=0 不代表浏览器直连；PAC 决定哪些站走代理）。SS 上游节点死掉时，被 PAC 路由的站点全挂、直连站点不受影响。诊断三连：`curl 直连` → `curl -x http://127.0.0.1:1080`（SOCKS）→ `curl -x http://127.0.0.1:9295`（ss_privoxy HTTP，注意是 9295 不是 1080）。修复=让用户在 SS 托盘换节点或取消"系统代理"；改 AutoConfigURL 注册表需要用户明确授权。另：Chrome 工具栏的 ZIO 等代理类扩展也要留意。
- **computer_use 驱动 Chrome 的两个硬约束**（2026-08-24 实踩）：① bare element index 点击会被拒（要 element_token 或 snapshot_id+element_index），坐标点击的缩放系数每次 capture 会变（实测 1.44x/2.12x 跳变）→ **切换标签页用键盘 Ctrl+数字**（如 Ctrl+2），别赌坐标；② 所有 key 组合对 Chrome 必须 `delivery_mode='foreground'`（background 会收到 background_unavailable 拒绝），前台投递会自动还原前台窗口，放心用。
- **千问 GUI 是最脆弱环节**：上传按钮/复制按钮位置可能随版本变，先 capture 找元素再点；代码块复制失败就退化为选中代码块文本复制。流式生成没完不能点复制。
- **OCR process 慢**：curl 超时设 120s+；process 返回数量应 = sync 数量，不符就查 ocr_image 表 status。
- **sync 幂等**：重复调 sync 不会重复建 ocr_image（按 file_upload_id 去重），但 batch-upload-from-disk 会把 Downloads 里所有 jpg 都上传——执行前确认 Downloads 里没有无关 jpg，或先把图片放到专用子目录再传该目录路径。
- **重复执行**：同一天重跑主线A前先检查 `## 涨停分析` 是否已有内容，有就先问用户是覆盖还是追加。
- **微信图片时效**：cache\images 里的图按 mtime 取，别拿成昨天的；必要时先清空或记录执行前最新 mtime。
- 后端不在跑时（8888 无监听）：告诉用户需要启动 investment-tool 后端，不要自己 mvn 启动除非用户同意。
