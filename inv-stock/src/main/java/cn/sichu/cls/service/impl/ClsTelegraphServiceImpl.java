package cn.sichu.cls.service.impl;

import cn.sichu.cls.component.ClsHttpClient;
import cn.sichu.cls.entity.ClsTelegraph;
import cn.sichu.cls.mapper.ClsTelegraphMapper;
import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.system.config.ProjectConfig;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.fasterxml.jackson.databind.JsonNode;
import enums.BusinessStatus;
import enums.TableLogic;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StreamUtils;
import utils.DateTimeUtils;
import utils.JsonUtils;
import utils.TradingDayUtils;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * @author sichu huang
 * @since 2026/01/03 16:20
 */

@Service
@RequiredArgsConstructor
@Slf4j
public class ClsTelegraphServiceImpl extends ServiceImpl<ClsTelegraphMapper, ClsTelegraph>
    implements IClsTelegraphService {
    private final ResourceLoader resourceLoader;
    private final ProjectConfig projectConfig;
    private final ClsHttpClient clsHttpClient;

    private static Thread getThread(Process process, StringBuilder errBuf) {
        Thread errThread = new Thread(() -> {
            try (BufferedReader br = new BufferedReader(
                new InputStreamReader(process.getErrorStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    errBuf.append(line).append('\n');
                }
            } catch (IOException ignored) {
            }
        });
        errThread.setDaemon(true);
        return errThread;
    }

    @Override
    public int fetchAndSaveAllRedTelegraphs() {
        List<JsonNode> items = fetchAllTelegraphItems();
        int savedCount = 0;
        for (JsonNode item : items) {
            if (isRedTelegraphItem(item)) {
                ClsTelegraph telegraph = saveTelegraph(item);
                if (telegraph != null) {
                    savedCount++;
                }
            }
        }
        log.info("CLS 加红电报拉取完成：新增 {} 条", savedCount);
        return savedCount;
    }

    @Override
    public boolean generateMarkdown(LocalDate today) {
        log.info("...开始生成 Markdown 文件, 日期: {}...", today);
        try {
            LocalDate targetDate;
            if (TradingDayUtils.isTradingDay(today)) {
                targetDate = today;
            } else {
                targetDate = TradingDayUtils.getNextTradingDay(today);
                if (targetDate == null) {
                    return false;
                }
            }

            String quarterDirName = DateTimeUtils.getQuarterStr(targetDate);
            Path dir = Paths.get(projectConfig.getMarkdown().getRootDir(), quarterDirName);
            Files.createDirectories(dir);

            String filename = targetDate.format(DateTimeUtils.YYYY_MM_DD) + ".md";
            Path markdownFile = dir.resolve(filename);

            boolean fileExisted = Files.exists(markdownFile);
            String content;

            if (!fileExisted) {
                String dayOfWeek = DateTimeUtils.getDayOfWeekCN(targetDate);
                String titleLine = targetDate.format(DateTimeUtils.YYYY_MM_DD) + " " + dayOfWeek;
                String baseTemplate = loadTemplateContent();
                content = "# " + titleLine + "\n\n" + baseTemplate;

                LocalDate prevTradingDay = TradingDayUtils.getPreviousTradingDay(targetDate);
                if (prevTradingDay != null) {
                    String inheritedHoldings = inheritHoldingsFromPrevious(prevTradingDay);
                    if (!inheritedHoldings.isEmpty()) {
                        content = content.replaceFirst("(### 当前持仓\\s*\n)",
                            "$1\n" + inheritedHoldings + "\n");
                    }
                }
            } else {
                content = Files.readString(markdownFile, StandardCharsets.UTF_8);
            }

            Files.writeString(markdownFile, content, StandardCharsets.UTF_8);
            log.info("Markdown 文件已更新: {}", markdownFile);
            return true;
        } catch (Exception e) {
            log.error("生成 Markdown 文件失败", e);
            return false;
        }
    }

    @Override
    public boolean appendRedTelegraphs(LocalDate date) {
        try {
            String quarterDirName = DateTimeUtils.getQuarterStr(date);
            Path dir = Paths.get(projectConfig.getMarkdown().getRootDir(), quarterDirName);
            String filename = date.format(DateTimeUtils.YYYY_MM_DD) + ".md";
            Path markdownFile = dir.resolve(filename);
            if (!Files.exists(markdownFile)) {
                log.warn("Markdown 文件不存在，无法追加电报: {}", markdownFile);
                return false;
            }

            LocalDate prevTradingDay = TradingDayUtils.getPreviousTradingDay(date);
            LocalDateTime start = null;
            if (prevTradingDay != null) {
                start = prevTradingDay.plusDays(1).atStartOfDay();
            }
            LocalDateTime end = date.plusDays(1).atStartOfDay();

            List<ClsTelegraph> telegraphs = baseMapper.selectRedTelegraphs("B", start, end);
            String content = Files.readString(markdownFile, StandardCharsets.UTF_8);
            String newTelegraphContent = buildTelegraphContent(telegraphs);
            // String updatedContent =  replaceTelegraphSection(content, newTelegraphContent);
            String updatedContent =
                replaceSection(content, "## 加红电报", "\n" + newTelegraphContent);

            Files.writeString(markdownFile, updatedContent, StandardCharsets.UTF_8);
            log.info("成功追加 {} 条加红电报到 {} (时间范围: {} ～ {})", telegraphs.size(),
                markdownFile, start, end);
            return true;
        } catch (Exception e) {
            log.error("追加加红电报失败: date={}", date, e);
            return false;
        }
    }

    /**
     * 发起 HTTP 请求并解析出 data.roll_data 列表
     *
     * @return java.util.List<com.fasterxml.jackson.databind.JsonNode>
     * @author sichu huang
     * @since 2026/01/08 16:46:17
     */
    private List<JsonNode> fetchAllTelegraphItems() {
        try {
            String rawResponse = clsHttpClient.fetchTelegraphList().block();
            if (rawResponse == null) {
                throw new RuntimeException("HTTP 响应为空");
            }

            JsonNode root = JsonUtils.parseFixedJson(rawResponse);
            if (!root.has("data") || !root.get("data").has("roll_data")) {
                throw new RuntimeException("JSON 结构异常，缺少 data.roll_data");
            }

            JsonNode rollData = root.get("data").get("roll_data");
            List<JsonNode> items = new ArrayList<>();
            if (rollData.isArray()) {
                for (JsonNode item : rollData) {
                    items.add(item);
                }
            }
            return items;
        } catch (Exception e) {
            log.error("拉取 CLS 电报列表失败", e);
            throw new RuntimeException("CLS 爬虫任务失败", e);
        }
    }

    /**
     * 保存电报, "cls_wp_", "cls_sp_", "cls_wjzt_", "cls_zt_" 自动 OCR 填充 md
     *
     * @param itemNode itemNode
     * @return cn.sichu.cls.entity.ClsTelegraph
     * @author sichu huang
     * @since 2026/01/08 16:48:57
     */
    @Transactional(rollbackFor = Exception.class)
    private ClsTelegraph saveTelegraph(JsonNode itemNode) {
        if (itemNode == null || !itemNode.has("id")) {
            log.warn("无效的电报节点，缺少 id");
            return null;
        }
        long clsId = itemNode.get("id").asLong();
        if (getByClsId(clsId) != null) {
            return null;
        }

        ClsTelegraph telegraph = new ClsTelegraph();
        telegraph.setClsId(clsId);
        telegraph.setTitle(itemNode.has("title") ? itemNode.get("title").asText(null) : null);
        telegraph.setBrief(itemNode.has("brief") ? itemNode.get("brief").asText(null) : null);
        telegraph.setContent(itemNode.has("content") ? itemNode.get("content").asText(null) : null);
        telegraph.setLevel(itemNode.has("level") ? itemNode.get("level").asText(null) : null);
        telegraph.setAuthor(itemNode.has("author") && !itemNode.get("author").isNull() ?
            itemNode.get("author").asText(null) : null);

        if (itemNode.has("ctime")) {
            long ctime = itemNode.get("ctime").asLong();
            telegraph.setPublishTime(LocalDateTime.ofEpochSecond(ctime, 0, ZoneOffset.ofHours(8)));
        }

        List<String> imageUrls = new ArrayList<>();
        if (itemNode.has("images") && itemNode.get("images").isArray()) {
            for (JsonNode urlNode : itemNode.get("images")) {
                if (urlNode.isTextual()) {
                    String url = urlNode.asText().trim();
                    if (url.startsWith("http") || url.startsWith("https")) {
                        imageUrls.add(url);
                    }
                }
            }
        }
        telegraph.setImages(imageUrls);
        telegraph.setStatus(BusinessStatus.SUCCESS.getCode());

        boolean saved = this.save(telegraph);
        if (saved) {
            log.info("新增电报: id={}, title={}", clsId, telegraph.getTitle());
            if (isWuPingItem(itemNode)) {
                downloadFirstImage(telegraph, "cls_wp_");
                ocrAndAppendMarkDown("wp", "午评");
            } else if (isShouPingItem(itemNode)) {
                downloadFirstImage(telegraph, "cls_sp_");
                ocrAndAppendMarkDown("sp", "收评");
            } else if (isWuJianZhangTingAnalysisItem(itemNode)) {
                downloadAllButLastImage(telegraph, "cls_wjzt_");
                ocrAndAppendMarkDown("wjzt", "午间涨停分析");
            } else if (isZhangTingAnalysisItem(itemNode)) {
                downloadAllButLastImage(telegraph, "cls_zt_");
                ocrAndAppendMarkDown("zt", "涨停分析");
            }
            return telegraph;
        }
        return null;
    }

    /**
     * 判断是否为 level == "B" 电报(加红电报)
     *
     * @param item 电报 JSON 节点
     * @return boolean
     * @author sichu huang
     * @since 2026/01/14 13:48:19
     */
    private boolean isRedTelegraphItem(JsonNode item) {
        if (item == null || !item.has("level")) {
            return false;
        }
        String level = item.get("level").asText("").trim();
        return "B".equalsIgnoreCase(level);
    }

    /**
     * 判断是否为“午评”电报
     *
     * @param item item
     * @return boolean
     * @author sichu huang
     * @since 2026/01/14 13:53:52
     */
    private boolean isWuPingItem(JsonNode item) {
        if (item == null || !item.has("title")) {
            return false;
        }
        String title = item.get("title").asText("").trim();
        return title.contains("午评");
    }

    /**
     * 判断是否为“M月d日午间涨停分析”电报
     *
     * @param item item
     * @return boolean
     * @author sichu huang
     * @since 2026/01/14 13:54:02
     */
    private boolean isWuJianZhangTingAnalysisItem(JsonNode item) {
        if (item == null || !item.has("title")) {
            return false;
        }
        String title = item.get("title").asText("").trim();
        Pattern pattern = Pattern.compile("(\\d{1,2}月\\d{1,2}日)午间涨停分析");
        Matcher matcher = pattern.matcher(title);
        if (!matcher.find()) {
            return false;
        }
        String datePart = matcher.group(1);
        String todayStr = LocalDate.now().format(DateTimeUtils.M_D_CHINESE);
        return todayStr.equals(datePart);
    }

    /**
     * 判断是否为“收评”电报
     *
     * @param item item
     * @return boolean
     * @author sichu huang
     * @since 2026/01/08 16:30:35
     */
    private boolean isShouPingItem(JsonNode item) {
        if (item == null || !item.has("title")) {
            return false;
        }
        String title = item.get("title").asText("").trim();
        return title.contains("收评");
    }

    /**
     * 判断是否为“M月d日涨停分析”电报
     *
     * @param item item
     * @return boolean
     * @author sichu huang
     * @since 2026/01/08 16:30:57
     */
    private boolean isZhangTingAnalysisItem(JsonNode item) {
        if (item == null || !item.has("title")) {
            return false;
        }
        String title = item.get("title").asText("").trim();

        Pattern pattern = Pattern.compile("(\\d{1,2}月\\d{1,2}日)涨停分析");
        Matcher matcher = pattern.matcher(title);
        if (!matcher.find()) {
            return false;
        }
        String datePart = matcher.group(1);
        String todayStr = LocalDate.now().format(DateTimeUtils.M_D_CHINESE);
        return todayStr.equals(datePart);
    }

    /**
     * 根据 clsId 查询
     *
     * @param clsId clsId
     * @return cn.sichu.cls.entity.ClsTelegraph
     * @author sichu huang
     * @since 2026/01/08 16:31:40
     */
    private ClsTelegraph getByClsId(Long clsId) {
        return this.getOne(new LambdaQueryWrapper<ClsTelegraph>().eq(ClsTelegraph::getClsId, clsId)
            .eq(ClsTelegraph::getIsDeleted, TableLogic.NOT_DELETED.getCode()));
    }

    /**
     * 通用图片下载方法
     *
     * @param telegraph      telegraph
     * @param filenamePrefix 下载的文件名前缀
     * @author sichu huang
     * @since 2026/01/08 17:00:29
     */
    private void downloadFirstImage(ClsTelegraph telegraph, String filenamePrefix) {
        List<String> imageUrls = telegraph.getImages();
        if (imageUrls == null || imageUrls.isEmpty()) {
            return;
        }

        String url = imageUrls.get(0);
        String timeStr = DateTimeUtils.getSecondStr(telegraph.getPublishTime());
        String ext = JsonUtils.getExtensionFromUrl(url);
        if (ext == null || ext.trim().isEmpty()) {
            ext = "jpg";
        }
        String filename = filenamePrefix + timeStr + "_1." + ext;
        String dateStr = DateTimeUtils.getDotDateStr(telegraph.getPublishTime());
        Path targetDir =
            Paths.get(projectConfig.getFile().getDownload().getRootDir(), "cls", dateStr);

        try {
            Files.createDirectories(targetDir);
            Path targetFile = targetDir.resolve(filename);
            downloadAndSaveImage(url, targetFile);
        } catch (IOException e) {
            log.error("创建下载目录失败: {}", targetDir, e);
        }
    }

    /**
     * 下载除最后一张外的所有图片
     *
     * @param telegraph      telegraph
     * @param filenamePrefix 下载的文件名前缀
     * @author sichu huang
     * @since 2026/01/12 16:44:05
     */
    private void downloadAllButLastImage(ClsTelegraph telegraph, String filenamePrefix) {
        List<String> imageUrls = telegraph.getImages();
        if (imageUrls == null) {
            imageUrls = Collections.emptyList();
        }

        if (imageUrls.size() <= 1) {
            downloadFirstImage(telegraph, filenamePrefix);
            return;
        }

        List<String> urlsToDownload = imageUrls.subList(0, imageUrls.size() - 1);
        String dateStr = DateTimeUtils.getDotDateStr(telegraph.getPublishTime());
        Path targetDir =
            Paths.get(projectConfig.getFile().getDownload().getRootDir(), "cls", dateStr);

        try {
            Files.createDirectories(targetDir);
            for (int i = 0; i < urlsToDownload.size(); i++) {
                String url = urlsToDownload.get(i);
                String timeStr = DateTimeUtils.getSecondStr(telegraph.getPublishTime());
                String ext = JsonUtils.getExtensionFromUrl(url);
                if (ext == null || ext.trim().isEmpty()) {
                    ext = "jpg";
                }
                String filename = filenamePrefix + timeStr + "_" + (i + 1) + "." + ext;
                Path targetFile = targetDir.resolve(filename);
                downloadAndSaveImage(url, targetFile);
            }
        } catch (IOException e) {
            log.error("创建图片下载目录失败: {}", targetDir, e);
        }
    }

    /**
     * 下载并保存单张图片
     *
     * @param url        url
     * @param targetFile targetFile
     * @author sichu huang
     * @since 2026/01/05 16:23:37
     */
    private void downloadAndSaveImage(String url, Path targetFile) {
        try {
            byte[] imageBytes = clsHttpClient.downloadImage(url).block();
            if (imageBytes == null || imageBytes.length == 0) {
                log.warn("图片下载为空，跳过: {}", url);
                return;
            }

            Files.write(targetFile, imageBytes, StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                StandardOpenOption.TRUNCATE_EXISTING);

            log.info("CLS 图片下载成功 | 保存路径={}", targetFile);
        } catch (Exception e) {
            log.error("单张图片下载失败: {}", url, e);
        }
    }

    /**
     * 加载模板
     *
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/14 12:44:11
     */
    private String loadTemplateContent() throws IOException {
        String location = projectConfig.getMarkdown().getTemplatePath();
        Resource resource = resourceLoader.getResource(location);
        if (!resource.exists()) {
            throw new IllegalStateException("Markdown 模板文件不存在: " + location);
        }
        return StreamUtils.copyToString(resource.getInputStream(), StandardCharsets.UTF_8);
    }

    /**
     * 从上一交易日 Markdown 中提取 "### 复盘持仓" 下的 #### 标题行
     *
     * @param prevDate prevDate
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/13 17:00:35
     */
    private String inheritHoldingsFromPrevious(LocalDate prevDate) {
        String quarterDirName = DateTimeUtils.getQuarterStr(prevDate);
        Path dir = Paths.get(projectConfig.getMarkdown().getRootDir(), quarterDirName);
        String filename = prevDate.format(DateTimeUtils.YYYY_MM_DD) + ".md";
        Path prevFile = dir.resolve(filename);

        if (!Files.exists(prevFile)) {
            log.warn("上一交易日文件不存在，无法继承持仓: {}", prevFile);
            return "";
        }

        try {
            String content = Files.readString(prevFile, StandardCharsets.UTF_8);
            int startIndex = content.indexOf("### 复盘持仓");
            if (startIndex == -1) {
                return "";
            }

            /* 从 "### 复盘持仓" 之后开始找 #### 行 */
            String afterSection = content.substring(startIndex + "### 复盘持仓".length());
            Pattern holdingPattern = Pattern.compile("^####\\s+[^|]+\\|.*$", Pattern.MULTILINE);
            Matcher matcher = holdingPattern.matcher(afterSection);

            StringBuilder holdings = new StringBuilder();
            while (matcher.find()) {
                String line = matcher.group().trim();
                holdings.append(line).append("\n");
            }

            return holdings.toString().trim();
        } catch (IOException e) {
            log.error("读取上一交易日文件失败: {}", prevFile, e);
            return "";
        }
    }

    /**
     * 构建md填充的电报内容
     *
     * @param telegraphs (List<ClsTelegraph>
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/14 13:00:06
     */
    private String buildTelegraphContent(List<ClsTelegraph> telegraphs) {
        if (telegraphs.isEmpty()) {
            return "\n";
        }
        StringBuilder sb = new StringBuilder();
        DateTimeFormatter dtf = DateTimeUtils.YYYY_MM_DD_HH_MM_SS;

        for (ClsTelegraph t : telegraphs) {
            String brief = Optional.ofNullable(t.getBrief()).orElse("");
            String content = Optional.ofNullable(t.getContent()).orElse("");
            String fullText = (!brief.isEmpty() ? brief : content);
            String cleanText = cleanLinkText(fullText);
            String timeStr = t.getPublishTime().format(dtf);
            String linkUrl = "https://www.cls.cn/detail/" + t.getClsId();
            sb.append("-   [").append(timeStr).append("] [").append(cleanText).append("](")
                .append(linkUrl).append(")\n");
            List<String> images = t.getImages();
            if (images != null && !images.isEmpty()) {
                for (String url : images) {
                    sb.append("    ![](").append(url).append(")\n");
                }
            }
        }
        return sb.toString();
    }

    /**
     * 清洗文本, 确保符合 Markdown 链接语法
     *
     * @param text text
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/16 17:49:18
     */
    private String cleanLinkText(String text) {
        if (text == null || text.trim().isEmpty()) {
            return "";
        }
        /* 1. 移除所有换行符、回车符，替换为单个空格 */
        String cleaned = text.replaceAll("[\\r\\n]+", " ");
        /* 2. 压缩多个连续空格为单个空格 */
        cleaned = cleaned.replaceAll("\\s+", " ");
        /* 3. 去除首尾空格 */
        cleaned = cleaned.trim();
        return cleaned;
    }

    /**
     * 替换 Markdown 中 "## 加红电报" 后的内容(直到下一个 ## 或 EOF)
     *
     * @param markdown   markdown
     * @param newContent newContent
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/14 13:00:54
     */
    // private String replaceTelegraphSection(String markdown, String newContent) {
    //     String marker = "## 加红电报";
    //     int markerIndex = markdown.indexOf(marker);
    //     if (markerIndex == -1) {
    //         /* 模板异常缺失, 兜底追加 */
    //         return markdown.trim() + "\n\n" + marker + "\n" + newContent;
    //     }
    //
    //     /* 找到 marker 行的结束位置(含换行) */
    //     int endOfMarkerLine = markdown.indexOf('\n', markerIndex);
    //     if (endOfMarkerLine == -1) {
    //         endOfMarkerLine = markdown.length();
    //     }
    //
    //     /* 找下一个二级标题或文件结尾 */
    //     int nextSection = markdown.indexOf("\n## ", endOfMarkerLine + 1);
    //     int contentEnd = (nextSection == -1) ? markdown.length() : nextSection;
    //
    //     String before = markdown.substring(0, endOfMarkerLine + 1);
    //     String after = markdown.substring(contentEnd);
    //     return before + "\n" + newContent + after;
    // }

    /**
     * cls 图下载成功后: OCR 解析 -> 填入当天 md 的对应 ## 小节
     * scripts/fill_cls_md.py; 解析器 scripts/cls_image_ocr.py
     * 失败只告警不写 md: 图不存在/python 非0退出(PARSE_FAIL);
     * 涨停分析=OCR 主题插在 ## 行后(人工手填沉底), 其它小节=整段复写
     *
     * @param imgSuffix   文件名 cls_{suffix}_HHmmss_1.*
     * @param sectionName md 小节名 午评/收评/午间涨停分析/涨停分析
     * @author sichu huang
     * @since 2026/09/25 15:23:19
     */
    private void ocrAndAppendMarkDown(String imgSuffix, String sectionName) {
        try {
            /* 1. 收集当天图: downloads/cls/yyyy.MM.dd/cls_{suffix}_时间戳_N.*
            同一天电报若重发会有多组时间戳, 只取最新一组, 组内按 N 升序 */
            String dateStr = DateTimeUtils.getDotDateStr(LocalDateTime.now());
            Path clsDir =
                Paths.get(projectConfig.getFile().getDownload().getRootDir(), "cls", dateStr);
            if (!Files.isDirectory(clsDir)) {
                log.warn("cls 图目录不存在, 跳过 OCR 填 md: {}", clsDir);
                return;
            }
            Pattern namePattern = Pattern.compile("cls_" + imgSuffix + "_(\\d{14})_(\\d+)\\..+");
            String latestTs = "";
            List<Path> imageFiles;
            Map<String, List<Path>> byTs = new HashMap<>();
            try (DirectoryStream<Path> stream = Files.newDirectoryStream(clsDir,
                "cls_" + imgSuffix + "_*_*.*")) {
                for (Path p : stream) {
                    Matcher m = namePattern.matcher(p.getFileName().toString());
                    if (m.matches()) {
                        byTs.computeIfAbsent(m.group(1), k -> new ArrayList<>()).add(p);
                        if (m.group(1).compareTo(latestTs) > 0) {
                            latestTs = m.group(1);
                        }
                    }
                }
            }
            if (byTs.isEmpty()) {
                log.warn("当天 {} 图不存在, 跳过 OCR 填 md: {}", imgSuffix, clsDir);
                return;
            }
            imageFiles = byTs.get(latestTs);
            /* 按序号 N 升序(_1 是大长图上半, _2 是下半...) */
            imageFiles.sort(Comparator.comparingInt(p -> {
                Matcher m = namePattern.matcher(p.getFileName().toString());
                return m.matches() ? Integer.parseInt(m.group(2)) : 0;
            }));

            /* 2. 定位当天 md
            涨停分析=OCR 主题插在 ## 行后(人工手填的 ### 如 ST 股沉底保持最后);
            其它小节(午评/收评/午间涨停分析)=整段复写, OCR 结果是该小节唯一权威内容 */
            LocalDate today = LocalDate.now();
            Path markdownFile = Paths.get(projectConfig.getMarkdown().getRootDir(),
                DateTimeUtils.getQuarterStr(today), today.format(DateTimeUtils.YYYY_MM_DD) + ".md");
            if (!Files.exists(markdownFile)) {
                log.warn("Markdown 文件不存在, 无法填入 {}: {}", sectionName, markdownFile);
                return;
            }
            String content = Files.readString(markdownFile, StandardCharsets.UTF_8);
            String marker = "## " + sectionName;
            String body = sectionBody(content, marker);
            if (body == null) {
                log.warn("md 中无 {} 小节, 跳过: {}", marker, markdownFile);
                return;
            }
            boolean isZt = "涨停分析".equals(sectionName);

            /* 3. 逐张调 python OCR(附录 B: 工作目录=项目根, 两流读干, 超时兜底), 任一 PARSE_FAIL 则整组不写(宁缺毋错) */
            Path projectRoot =
                Paths.get(projectConfig.getFile().getDownload().getRootDir()).getParent();
            StringBuilder merged = new StringBuilder();
            for (Path imageFile : imageFiles) {
                Path venvPy = projectRoot.resolve("scripts/venv/Scripts/python.exe");
                String pythonExe = Files.isRegularFile(venvPy) ? venvPy.toString() : "python";
                ProcessBuilder pb = new ProcessBuilder(pythonExe,
                    projectRoot.resolve("scripts/cls/cls_image_ocr.py").toString(),
                    imageFile.toString(), "--type", imgSuffix);
                pb.directory(projectRoot.toFile());
                Process process = pb.start();
                /* stderr 起线程读干, 防缓冲区满死锁 */
                StringBuilder errBuf = new StringBuilder();
                Thread errThread = getThread(process, errBuf);
                errThread.start();
                /* stdout 必须 UTF-8: python 侧已 reconfigure, 默认 GBK 读会乱码 */
                StringBuilder outBuf = new StringBuilder();
                try (BufferedReader br = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = br.readLine()) != null) {
                        outBuf.append(line).append('\n');
                    }
                }
                boolean finished = process.waitFor(5, TimeUnit.MINUTES);
                if (!finished) {
                    process.destroyForcibly();
                    log.warn("OCR 超时(5min), 整组跳过: {} {}", sectionName, imageFile);
                    return;
                }
                if (process.exitValue() != 0) {
                    log.warn("OCR PARSE_FAIL: {} {} | {}", sectionName, imageFile.getFileName(),
                        errBuf.toString().trim());
                    return;
                }
                String one = outBuf.toString().trim();
                if (one.isEmpty()) {
                    log.warn("OCR 输出为空, 整组跳过: {} {}", sectionName, imageFile.getFileName());
                    return;
                }
                if (!merged.isEmpty()) {
                    merged.append("\n\n");
                }
                merged.append(one);
            }

            /* 4. 写盘: 涨停分析=插入合并; 其它小节=整段复写 */
            String updated;
            if (isZt) {
                String mergedBody = mergeSubsections(body, merged.toString());
                if (mergedBody == null) {
                    log.info("{} 小节全部 OCR 主题已存在, 无新增", marker);
                    return;
                }
                updated = replaceSection(content, marker, "\n" + mergedBody + "\n");
            } else {
                updated = replaceSection(content, marker, "\n" + merged + "\n");
            }
            Files.writeString(markdownFile, updated, StandardCharsets.UTF_8);
            log.info("OCR 填入 {} 成功, 共 {} 张图 <- 最新组 {}{}", marker, imageFiles.size(),
                latestTs, isZt ? "(插入合并)" : "(整段复写)");
        } catch (Exception e) {
            log.error("OCR 填 md 失败: {} {}", imgSuffix, sectionName, e);
        }
    }

    /**
     * 涨停分析专用插入合并
     * 现有内容之前——人工手填的小节(如 ### ST 股)沉底保持最后;
     * 已存在的 ### 主题跳过(同日重发电报幂等); 无 ### 的 OCR 前言不插。
     *
     * @param body    现有小节正文
     * @param ocrText OCR 产出(若干 "### 主题" 块)
     * @return 合并后正文; 无新增返回 null
     * @author sichu huang
     * @since 2026/09/28 19:30:00
     */
    private String mergeSubsections(String body, String ocrText) {
        Set<String> existing = new HashSet<>();
        for (String line : body.split("\n")) {
            String t = line.trim();
            if (t.startsWith("### ")) {
                existing.add(t.substring(4).replace(" ", "").toLowerCase());
            }
        }
        List<String> blocks = new ArrayList<>();
        StringBuilder cur = null;
        for (String line : ocrText.split("\n")) {
            if (line.trim().startsWith("### ")) {
                if (cur != null) {
                    blocks.add(cur.toString());
                }
                cur = new StringBuilder();
            }
            if (cur != null) {
                cur.append(line).append('\n');
            }
        }
        if (cur != null) {
            blocks.add(cur.toString());
        }
        StringBuilder head = new StringBuilder();
        List<String> added = new ArrayList<>();
        for (String b : blocks) {
            String firstLine = b.lines().findFirst().orElse("").trim();
            String title = firstLine.substring(4).replace(" ", "").toLowerCase();
            if (existing.contains(title)) {
                continue;
            }
            if (head.length() > 0) {
                head.append("\n\n");
            }
            head.append(b.strip());
            added.add(title);
        }
        if (added.isEmpty()) {
            return null;
        }
        log.info("合并填入 {} 个新主题: {}", added.size(), added);
        String rest = body.strip();
        return rest.isEmpty() ? head.toString() : head + "\n\n" + rest;
    }

    /**
     * 取 marker 小节正文(marker 行到下一个 ## 行之间), 无小节返回 null
     *
     * @param markdown markdown
     * @param marker   如 "## 午评"
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/09/25 15:37:25
     */
    private String sectionBody(String markdown, String marker) {
        int markerIndex = markdown.indexOf(marker);
        if (markerIndex == -1) {
            return null;
        }
        int endOfMarkerLine = markdown.indexOf('\n', markerIndex);
        if (endOfMarkerLine == -1) {
            return "";
        }
        int nextSection = markdown.indexOf("\n## ", endOfMarkerLine + 1);
        int contentEnd = (nextSection == -1) ? markdown.length() : nextSection;
        return markdown.substring(endOfMarkerLine + 1, contentEnd);
    }

    /**
     * 替换 marker 小节正文
     *
     * @param markdown   markdown
     * @param marker     如 "## 午评"
     * @param newContent 新正文(含首尾换行)
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/09/25 15:38:22
     */
    private String replaceSection(String markdown, String marker, String newContent) {
        int markerIndex = markdown.indexOf(marker);
        if (markerIndex == -1) {
            /* 模板异常缺失, 兜底追加 */
            return markdown.trim() + "\n\n" + marker + "\n" + newContent;
        }
        int endOfMarkerLine = markdown.indexOf('\n', markerIndex);
        if (endOfMarkerLine == -1) {
            endOfMarkerLine = markdown.length();
        }
        int nextSection = markdown.indexOf("\n## ", endOfMarkerLine + 1);
        int contentEnd = (nextSection == -1) ? markdown.length() : nextSection;
        String before = markdown.substring(0, endOfMarkerLine + 1);
        String after = markdown.substring(contentEnd);
        return before + newContent + after;
    }

    @Override
    public String cleanupLocalImages(int retentionDays) {
        Path clsDir = Paths.get(projectConfig.getFile().getDownload().getRootDir(), "cls");
        if (!Files.isDirectory(clsDir)) {
            return "cls 图片目录不存在, 跳过";
        }
        LocalDate cutoff = LocalDate.now().minusDays(retentionDays);
        int removed = 0, failed = 0;
        try (Stream<Path> dirs = Files.list(clsDir)) {
            for (Path dayDir : dirs.filter(Files::isDirectory).toList()) {
                try {
                    /* 非日期目录跳过 */
                    if (LocalDate.parse(dayDir.getFileName().toString(), DateTimeUtils.YYYYMMDD_DOT)
                        .isBefore(cutoff)) {
                        try (Stream<Path> walk = Files.walk(dayDir)) {
                            for (Path p : walk.sorted(Comparator.reverseOrder()).toList()) {
                                Files.deleteIfExists(p);
                            }
                        }
                        removed++;
                    }
                } catch (DateTimeParseException e) {
                    /* 非日期目录, 跳过 */
                } catch (Exception e) {
                    log.error("cls 图片目录删除失败 {}: {}", dayDir, e.getMessage());
                    failed++;
                }
            }
        } catch (Exception e) {
            return "cls 图片清理异常: " + e.getMessage();
        }
        return String.format("cls图片清理 %d 个日期目录/失败 %d", removed, failed);
    }
}
