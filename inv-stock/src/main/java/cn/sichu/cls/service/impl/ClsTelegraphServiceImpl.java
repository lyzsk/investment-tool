package cn.sichu.cls.service.impl;

import cn.sichu.cls.component.ClsHttpClient;
import cn.sichu.cls.entity.ClsTelegraph;
import cn.sichu.cls.mapper.ClsTelegraphMapper;
import cn.sichu.cls.service.IClsTelegraphService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.fasterxml.jackson.databind.JsonNode;
import config.ProjectConfig;
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
import utils.MarkdownUtils;
import utils.TradingDayUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

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
        log.info("CLS 加红电报(B级)拉取完成：新增 {} 条", savedCount);
        return savedCount;
    }

    @Override
    public int fetchAndSaveShouPingTelegraphs() {
        List<JsonNode> items = fetchAllTelegraphItems();
        int savedCount = 0;
        for (JsonNode item : items) {
            if (isShouPingItem(item)) {
                ClsTelegraph telegraph = saveTelegraph(item);
                if (telegraph != null) {
                    savedCount++;
                    downloadFirstImage(telegraph, "cls_sp_");
                }
            }
        }
        log.info("CLS 收评电报拉取完成：{} 条", savedCount);
        return savedCount;
    }

    @Override
    public int fetchAndSaveZhangTingTelegraphs() {
        List<JsonNode> items = fetchAllTelegraphItems();
        int savedCount = 0;
        for (JsonNode item : items) {
            if (isZhangTingAnalysisItem(item)) {
                ClsTelegraph telegraph = saveTelegraph(item);
                if (telegraph != null) {
                    savedCount++;
                    downloadAllButLastImage(telegraph, "cls_zt_");
                }
            }
        }
        log.info("CLS 涨停分析电报拉取完成：{} 条", savedCount);
        return savedCount;
    }

    @Override
    public boolean generateMarkdown(LocalDate today) {
        try {
            LocalDate nextTradingDay = TradingDayUtils.getNextTradingDay(today);
            log.info("准备为下一个交易日 {} 生成 Markdown 文件", nextTradingDay);

            Path dir = Paths.get(projectConfig.getMarkdown().getRootDir());
            Files.createDirectories(dir);

            String filename = nextTradingDay.format(DateTimeUtils.YYYY_MM_DD) + ".md";
            Path markdownFile = dir.resolve(filename);

            boolean fileExisted = Files.exists(markdownFile);
            String content;

            if (!fileExisted) {
                /* 初始化模板 + 继承持仓 */
                String dayOfWeek = DateTimeUtils.getDayOfWeekCN(nextTradingDay);
                String titleLine =
                    nextTradingDay.format(DateTimeUtils.YYYY_MM_DD) + " " + dayOfWeek;
                String baseTemplate = loadTemplateContent();
                content = "# " + titleLine + "\n\n" + baseTemplate;

                /* 从上一交易日继承持仓标题 */
                LocalDate prevTradingDay = TradingDayUtils.getPreviousTradingDay(nextTradingDay);
                if (prevTradingDay != null) {
                    String inheritedHoldings = inheritHoldingsFromPrevious(prevTradingDay);
                    if (!inheritedHoldings.isEmpty()) {
                        /* 替换 "### 当前持仓" 后的内容 */
                        content = content.replaceFirst("(### 当前持仓\\s*\n)",
                            "$1" + inheritedHoldings + "\n");
                    }
                }
            } else {
                /* 文件已存在: 读取现有内容 */
                content = Files.readString(markdownFile, StandardCharsets.UTF_8);
            }

            /* 写回文件 */
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
            Path dir = Paths.get(projectConfig.getMarkdown().getRootDir());
            String filename = date.format(DateTimeUtils.YYYY_MM_DD) + ".md";
            Path markdownFile = dir.resolve(filename);

            if (!Files.exists(markdownFile)) {
                log.warn("Markdown 文件不存在，无法追加电报: {}", markdownFile);
                return false;
            }

            String content = Files.readString(markdownFile, StandardCharsets.UTF_8);

            LocalDateTime start = date.atStartOfDay();
            LocalDateTime end = date.plusDays(1).atStartOfDay();
            List<ClsTelegraph> telegraphs = baseMapper.selectRedTelegraphs("B", start, end);
            log.debug("Telegraph images: {}", telegraphs.get(0).getImages());
            String newTelegraphContent = buildTelegraphContent(telegraphs);
            String formattedContent = MarkdownUtils.format(newTelegraphContent);
            String updatedContent = replaceTelegraphSection(content, formattedContent);

            Files.writeString(markdownFile, updatedContent, StandardCharsets.UTF_8);
            log.info("成功追加 {} 条加红电报到 {}", telegraphs.size(), markdownFile);
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
     * 保存电报
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

        LocalDateTime now = LocalDateTime.now();
        telegraph.setCreateTime(now);
        telegraph.setUpdateTime(now);
        telegraph.setStatus(BusinessStatus.SUCCESS.getCode());

        boolean saved = this.save(telegraph);
        if (saved) {
            log.info("新增电报: id={}, title={}", clsId, telegraph.getTitle());
            if (isWuPingItem(itemNode)) {
                downloadFirstImage(telegraph, "cls_wp_");
            } else if (isShouPingItem(itemNode)) {
                downloadFirstImage(telegraph, "cls_sp_");
            } else if (isWuJianZhangTingAnalysisItem(itemNode)) {
                downloadAllButLastImage(telegraph, "cls_wjzt_");
            } else if (isZhangTingAnalysisItem(itemNode)) {
                downloadAllButLastImage(telegraph, "cls_zt_");
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
            log.debug("电报无图片可下载: id={}, title={}", telegraph.getClsId(),
                telegraph.getTitle());
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
        Path targetDir = Paths.get(projectConfig.getFileDownload().getRootDir(), "cls", dateStr);

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
        Path targetDir = Paths.get(projectConfig.getFileDownload().getRootDir(), "cls", dateStr);

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
        Path dir = Paths.get(projectConfig.getMarkdown().getRootDir());
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
            String timeStr = t.getPublishTime().format(dtf);
            String linkUrl = "https://www.cls.cn/detail/" + t.getClsId();
            sb.append("-   [").append(timeStr).append("] [").append(fullText).append("](")
                .append(linkUrl).append(")\n");
            List<String> images = t.getImages();
            log.debug("Processing telegraph id={}, images={}", t.getClsId(), t.getImages());
            if (images != null && !images.isEmpty()) {
                for (String url : images) {
                    sb.append("    ![](").append(url).append(")\n");
                }
            }
        }
        return sb.toString();
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
    private String replaceTelegraphSection(String markdown, String newContent) {
        String marker = "## 加红电报";
        int markerIndex = markdown.indexOf(marker);
        if (markerIndex == -1) {
            /* 模板异常缺失, 兜底追加 */
            return markdown.trim() + "\n\n" + marker + "\n" + newContent;
        }

        /* 找到 marker 行的结束位置(含换行) */
        int endOfMarkerLine = markdown.indexOf('\n', markerIndex);
        if (endOfMarkerLine == -1)
            endOfMarkerLine = markdown.length();

        /* 找下一个二级标题或文件结尾 */
        int nextSection = markdown.indexOf("\n## ", endOfMarkerLine + 1);
        int contentEnd = (nextSection == -1) ? markdown.length() : nextSection;

        String before = markdown.substring(0, endOfMarkerLine + 1);
        String after = markdown.substring(contentEnd);
        return before + newContent + after;
    }
}
