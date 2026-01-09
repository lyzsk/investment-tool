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
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import utils.DateTimeUtils;
import utils.JsonUtils;
import utils.StringUtils;

import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
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
    private static final Pattern ZT_ANALYSIS_PATTERN =
        Pattern.compile("(\\d{1,2}月\\d{1,2}日)涨停分析");
    private final ProjectConfig projectConfig;

    @Override
    public int fetchAndSaveLatestTelegraphs() {
        List<JsonNode> items = fetchAllTelegraphItems();
        int savedCount = 0;
        for (JsonNode item : items) {
            ClsTelegraph telegraph = saveTelegraph(item);
            if (telegraph != null) {
                savedCount++;
            }
        }
        log.info("CLS 电报拉取完成：新增 {} 条", savedCount);
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
                    downloadFirstImage(telegraph, "cls_zt_");
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
            if (isZhangTingAnalysisTodayItem(item)) {
                ClsTelegraph telegraph = saveTelegraph(item);
                if (telegraph != null) {
                    savedCount++;
                    downloadFirstImage(telegraph, "cls_zt_");
                }
            }
        }
        log.info("CLS 涨停分析电报拉取完成：{} 条", savedCount);
        return savedCount;
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
            String rawResponse = new ClsHttpClient().fetchTelegraphList().block();
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
            telegraph.setPublishTime(
                LocalDateTime.ofEpochSecond(ctime, 0, java.time.ZoneOffset.ofHours(8)));
        }

        try {
            telegraph.setRawData(JsonUtils.objectMapper.writeValueAsString(itemNode));
        } catch (Exception e) {
            log.error("序列化原始 JSON 失败", e);
            telegraph.setRawData("{}");
        }

        LocalDateTime now = LocalDateTime.now();
        telegraph.setCreateTime(now);
        telegraph.setUpdateTime(now);
        telegraph.setStatus(BusinessStatus.SUCCESS.getCode());

        boolean saved = this.save(telegraph);
        if (saved) {
            log.info("新增电报: id={}, title={}", clsId, telegraph.getTitle());
            return telegraph;
        }
        return null;
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
    private boolean isZhangTingAnalysisTodayItem(JsonNode item) {
        if (item == null || !item.has("title")) {
            return false;
        }
        String title = item.get("title").asText("").trim();
        Matcher matcher = ZT_ANALYSIS_PATTERN.matcher(title);
        if (!matcher.find()) {
            return false;
        }
        String datePart = matcher.group(1);
        String todayStr = LocalDate.now().format(DateTimeFormatter.ofPattern("M月d日"));
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
     * @param filenamePrefix filenamePrefix
     * @author sichu huang
     * @since 2026/01/08 17:00:29
     */
    private void downloadFirstImage(ClsTelegraph telegraph, String filenamePrefix) {
        List<String> imageUrls = extractImageUrls(telegraph.getRawData());
        if (imageUrls.isEmpty()) {
            log.debug("电报无图片可下载: id={}, title={}", telegraph.getClsId(),
                telegraph.getTitle());
            return;
        }

        String url = imageUrls.get(0);
        String timeStr = DateTimeUtils.getSecondStr(telegraph.getPublishTime());
        String ext = extractRawExtensionFromUrl(url);
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
     * 从 URL 中提取原始扩展名(不校验合法性, 不转换jpeg->jpg)
     *
     * @param url url
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/06 16:20:46
     */
    private String extractRawExtensionFromUrl(String url) {
        if (StringUtils.isEmpty(url)) {
            return null;
        }
        try {
            URI uri = new URI(url);
            String path = uri.getPath();
            if (path == null || path.isEmpty()) {
                return null;
            }
            int lastDotIndex = path.lastIndexOf('.');
            if (lastDotIndex > 0 && lastDotIndex < path.length() - 1) {
                String ext = path.substring(lastDotIndex + 1).toLowerCase();
                if (ext.matches("[a-zA-Z0-9]+")) {
                    return ext;
                }
            }
            return null;
        } catch (URISyntaxException e) {
            return null;
        }
    }

    /**
     * 解析 JSON 获取图片 URL 列表
     *
     * @param rawData rawData
     * @return java.util.List<java.lang.String>
     * @author sichu huang
     * @since 2026/01/05 16:23:05
     */
    private List<String> extractImageUrls(String rawData) {
        if (StringUtils.isEmpty(rawData)) {
            return Collections.emptyList();
        }
        try {
            JsonNode node = JsonUtils.objectMapper.readTree(rawData);
            if (!node.has("images") || !node.get("images").isArray()) {
                return Collections.emptyList();
            }
            List<String> urls = new ArrayList<>();
            for (JsonNode urlNode : node.get("images")) {
                if (urlNode.isTextual()) {
                    String url = urlNode.asText().trim();
                    if (url.startsWith("http")) {
                        urls.add(url);
                    }
                }
            }
            return urls;
        } catch (Exception e) {
            log.warn("解析 rawData 中的 images 失败", e);
            return Collections.emptyList();
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
            byte[] imageBytes = new ClsHttpClient().downloadImage(url).block();
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
}
