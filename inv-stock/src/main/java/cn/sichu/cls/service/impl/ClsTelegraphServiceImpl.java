package cn.sichu.cls.service.impl;

import cn.sichu.cls.component.ClsHttpClient;
import cn.sichu.cls.entity.ClsTelegraph;
import cn.sichu.cls.mapper.ClsTelegraphMapper;
import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.cls.utils.JsonFixUtils;
import cn.sichu.system.file.utils.FileUtils;
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
import utils.StringUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
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
        Pattern.compile("\\d{1,2}月\\d{1,2}日涨停分析");
    private final ProjectConfig projectConfig;

    @Override
    public ClsTelegraph getByClsId(Long clsId) {
        return this.getOne(new LambdaQueryWrapper<ClsTelegraph>().eq(ClsTelegraph::getClsId, clsId)
            .eq(ClsTelegraph::getIsDeleted, TableLogic.NOT_DELETED.getCode()));
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public boolean saveOrUpdateFromRaw(JsonNode itemNode) {
        if (itemNode == null || !itemNode.has("id")) {
            log.warn("无效的电报节点，缺少 id");
            return false;
        }
        long clsId = itemNode.get("id").asLong();
        if (getByClsId(clsId) != null) {
            return false;
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
            /* CLS 的 ctime 是秒级时间戳（如 1767424783）*/
            telegraph.setPublishTime(
                LocalDateTime.ofEpochSecond(ctime, 0, java.time.ZoneOffset.ofHours(8)));
        }
        try {
            telegraph.setRawData(JsonFixUtils.objectMapper.writeValueAsString(itemNode));
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
            downloadImagesToLocal(telegraph);
        }
        return saved;
    }

    @Override
    public void fetchAndSaveLatestTelegraphs() {
        try {
            String rawResponse = new ClsHttpClient().fetchTelegraphList().block();
            if (rawResponse == null) {
                throw new RuntimeException("HTTP 响应为空");
            }

            JsonNode root = JsonFixUtils.parseFixedJson(rawResponse);
            if (!root.has("data") || !root.get("data").has("roll_data")) {
                throw new RuntimeException("JSON 结构异常，缺少 data.roll_data");
            }

            JsonNode rollData = root.get("data").get("roll_data");
            int savedCount = 0;

            for (JsonNode item : rollData) {
                if (!shouldProcessItem(item)) {
                    continue;
                }
                if (saveOrUpdateFromRaw(item)) {
                    savedCount++;
                }
            }

            log.info("本次拉取 {} 条电报，新增 {} 条", rollData.size(), savedCount);

        } catch (Exception e) {
            log.error("拉取并保存 CLS 电报失败", e);
            throw new RuntimeException("CLS 爬虫任务失败", e);
        }
    }

    /**
     * 判断是否应处理该电报项
     * 1. 标题包含 "收评"
     * 2. 标题包含 "X月X日涨停分析"
     *
     * @param item item
     * @return boolean
     * @author sichu huang
     * @since 2026/01/03 17:49:18
     */
    private boolean shouldProcessItem(JsonNode item) {
        if (item == null || !item.has("title")) {
            return false;
        }
        String title = item.get("title").asText("").trim();
        if (title.contains("收评")) {
            return true;
        }
        Matcher matcher = ZT_ANALYSIS_PATTERN.matcher(title);
        if (matcher.find()) {
            String datePart = matcher.group(1);
            LocalDate today = LocalDate.now();
            String todayStr = today.format(DateTimeFormatter.ofPattern("M月d日"));
            return todayStr.equals(datePart);
        }
        return false;
    }

    /**
     * 下载到本地
     * 1. 解析 rawData 获取 imgs
     * 2. 确定要下载的 URL 列表
     * 3. 构建目标目录：downloads/cls/yyyy.MM.dd/
     *
     * @param telegraph ClsTelegraph
     * @author sichu huang
     * @since 2026/01/03 18:19:22
     */
    private void downloadImagesToLocal(ClsTelegraph telegraph) {
        try {
            String title = telegraph.getTitle();
            if (StringUtils.isEmpty(title)) {
                return;
            }

            boolean isShouPing = title.contains("收评");
            boolean isZtAnalysis = ZT_ANALYSIS_PATTERN.matcher(title).find();
            if (!isShouPing && !isZtAnalysis) {
                return;
            }
            // 1. 解析 rawData 获取 imgs
            String rawData = telegraph.getRawData();
            if (StringUtils.isEmpty(rawData)) {
                return;
            }
            JsonNode rootNode = JsonFixUtils.objectMapper.readTree(rawData);
            List<String> imageUrls = new ArrayList<>();
            // 优先从 imgs 字段提取
            if (rootNode.has("imgs") && rootNode.get("imgs").isArray()) {
                for (JsonNode node : rootNode.get("imgs")) {
                    if (node.isTextual()) {
                        String url = node.asText().trim();
                        if (url.startsWith("http")) {
                            imageUrls.add(url);
                        }
                    }
                }
            }
            if (imageUrls.isEmpty() && rootNode.has("images") && rootNode.get("images").isArray()) {
                for (JsonNode node : rootNode.get("images")) {
                    if (node.isTextual()) {
                        String url = node.asText().trim();
                        if (url.startsWith("http")) {
                            imageUrls.add(url);
                        }
                    }
                }
            }
            if (imageUrls.isEmpty()) {
                log.debug("电报无图片可下载: id={}, title={}", telegraph.getClsId(), title);
                return;
            }
            // 2. 确定要下载的 URL 列表
            List<String> urlsToDownload = isShouPing ? imageUrls : List.of(imageUrls.get(0));

            // 3. 构建目标目录：downloads/cls/yyyy.MM.dd/
            String downloadRootDir = projectConfig.getFileDownload().getRootDir();
            Path downloadsRoot = Paths.get(downloadRootDir).resolve("cls");
            String dateStr = telegraph.getPublishTime().toLocalDate()
                .format(DateTimeFormatter.ofPattern("yyyy.MM.dd"));
            Path targetDir = downloadsRoot.resolve(dateStr);

            // 创建目录
            Files.createDirectories(targetDir);

            // 4. 下载每张图片
            for (int i = 0; i < urlsToDownload.size(); i++) {
                String imgUrl = urlsToDownload.get(i);
                try {
                    byte[] imageBytes = new ClsHttpClient().downloadImage(imgUrl).block();
                    if (imageBytes == null || imageBytes.length == 0) {
                        log.warn("图片下载为空，跳过: {}", imgUrl);
                        continue;
                    }

                    // 推断扩展名
                    String ext = FileUtils.guessExtensionFromUrl(imgUrl);
                    if (ext == null) {
                        // 尝试从 magic bytes 判断（可选），这里简化用 jpg
                        ext = "jpg";
                    }

                    // 文件名：cls_{clsId}_{index}.{ext}
                    String filename =
                        String.format("cls_%d_%d.%s", telegraph.getClsId(), i + 1, ext);
                    Path targetFile = targetDir.resolve(filename);

                    // 写入文件
                    Files.write(targetFile, imageBytes, StandardOpenOption.CREATE,
                        StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING);

                    log.info("CLS 图片下载成功 | 电报ID={} | 保存路径={}", telegraph.getClsId(),
                        targetFile);

                } catch (Exception e) {
                    log.error("单张图片下载失败: {}", imgUrl, e);
                }
            }

        } catch (Exception e) {
            log.error("下载 CLS 电报图片到本地失败, 电报ID={}", telegraph.getClsId(), e);
        }
    }
}
