package cn.sichu.bilibili.service.impl;

import cn.sichu.bilibili.entity.BilibiliVideo;
import cn.sichu.bilibili.service.IBilibiliReconcileService;
import cn.sichu.bilibili.service.IBilibiliVideoService;
import cn.sichu.reconcile.entity.ReconcileResult;
import cn.sichu.reconcile.service.IReconcileResultService;
import cn.sichu.system.config.ProjectConfig;
import com.fasterxml.jackson.databind.JsonNode;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import utils.DateTimeUtils;
import utils.JsonUtils;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Slf4j
@Service
@RequiredArgsConstructor
public class BilibiliReconcileServiceImpl implements IBilibiliReconcileService {
    private static final String BIZ = "BILIBILI";
    private static final ZoneId CN = ZoneId.of("Asia/Shanghai");
    private static final Pattern BVID_IN_MD = Pattern.compile("bilibili\\.com/video/(BV[0-9A-Za-z]{10})");
    private static final Pattern MD_NAME = Pattern.compile("(\\d{4}-\\d{2}-\\d{2})\\.md");
    /* 发布不满 30h 的视频还在当晚 check md 窗口内, 缺 sum/distill 只记待办不算缺口 */
    private static final long GRACE_HOURS = 30;
    /* step 先后(推进只往后不回退); DOWNLOADING/PROCESSING 是租约态, 对账不碰 */
    private static final List<String> STEP_ORDER =
        List.of("NEW", "DOWNLOADING", "DOWNLOADED", "PROCESSING", "VISION_DONE", "SUMMARIZED", "DISTILLED");
    private static final Set<String> LEASED = Set.of("DOWNLOADING", "PROCESSING");
    /* detail 里最多列几条 */
    private static final int LIST_MAX = 30;

    private final ProjectConfig projectConfig;
    private final IBilibiliVideoService bilibiliVideoService;
    private final IReconcileResultService reconcileResultService;

    @Override
    public String reconcile() throws Exception {
        String batchNo = reconcileResultService.newBatchNo(BIZ);
        Map<String, TreeSet<LocalDate>> mdIndex = scanMd();
        List<ReconcileResult> rows = new ArrayList<>();
        Iterator<Map.Entry<String, JsonNode>> it = readUps().fields();
        while (it.hasNext()) {
            Map.Entry<String, JsonNode> up = it.next();
            rows.addAll(reconcileUp(batchNo, up.getKey(), up.getValue(), mdIndex));
        }
        return reconcileResultService.saveAndNotify("UP 视频管线对账", rows);
    }

    /**
     * 单个 UP 的对账+DB 同步
     *
     * @author sichu huang
     * @param batchNo batchNo
     * @param up up
     * @param cfg cfg
     * @param mdIndex bvid → 出现过的 md 日
     * @since 2026/10/12
     * @return java.util.List<cn.sichu.reconcile.entity.ReconcileResult>
     **/
    private List<ReconcileResult> reconcileUp(String batchNo, String up, JsonNode cfg,
        Map<String, TreeSet<LocalDate>> mdIndex) throws Exception {
        String mid = cfg.path("mid").asText();
        Set<LocalDate> distilled = readDistilled(cfg);
        Map<String, JsonNode> index = readIndex(cfg);
        Map<String, VideoFiles> files = scanResults(mid);
        Map<String, BilibiliVideo> db = bilibiliVideoService.lambdaQuery().eq(BilibiliVideo::getAuthorMid, mid).list()
            .stream().collect(Collectors.toMap(BilibiliVideo::getBvid, Function.identity(), (a, b) -> a));
        LocalDateTime graceFrom = LocalDateTime.now().minusHours(GRACE_HOURS);
        List<String> sumMissing = new ArrayList<>();
        List<String> distillMissing = new ArrayList<>();
        List<String> pending = new ArrayList<>();
        Set<LocalDate> resultDays = new TreeSet<>();
        Set<LocalDate> sumDays = new TreeSet<>();
        Set<LocalDate> distillDays = new TreeSet<>();
        int inserted = 0;
        int advanced = 0;
        /* 10/24: 用户确认跳过的视频(remark 含"跳过"且 retry_count>=3, 如天哥 BV1cN19YuECh 生活 vlog) sum / distill 也不再报缺 */
        Set<String> skippedBvids = db.values().stream()
            .filter(v -> v.getRetryCount() != null && v.getRetryCount() >= 3 && v.getRemark() != null && v.getRemark().contains("跳过"))
            .map(BilibiliVideo::getBvid).collect(Collectors.toSet());
        for (VideoFiles f : files.values()) {
            if (!f.full) {
                continue;
            }
            resultDays.add(f.day);
            BilibiliVideo row = db.get(f.bvid);
            LocalDateTime pub = row != null ? row.getPublishTime() : publishTimeOf(index.get(f.bvid), f.day);
            boolean grace = pub.isAfter(graceFrom);
            TreeSet<LocalDate> mdDates = mdIndex.getOrDefault(f.bvid, new TreeSet<>());
            Set<LocalDate> doneDates = mdDates.stream().filter(distilled::contains).collect(Collectors.toSet());
            /* 非交易日稿顺延挂下一交易日 md, 单独蒸馏时账本记的是发布日;
             * 10/17: 挂载日先蒸馏、顺延块后并入再单独蒸馏(rolled_pending)时, 账本里发布日和挂载日都有,
             * 原条件 doneDates.isEmpty() 让发布日落不进 distillDays → 误报 orphan_distill(如 taoge 2026-09-13) */
            if (!mdDates.isEmpty() && distilled.contains(f.day)) {
                doneDates.add(f.day);
            }
            String expected = mdDates.isEmpty() ? "VISION_DONE" : doneDates.isEmpty() ? "SUMMARIZED" : "DISTILLED";
            if (skippedBvids.contains(f.bvid)) {
                /* 10/24: 用户确认跳过, 不算 sum / distill 缺(db_skipped 一行照旧列出) */
            } else if (mdDates.isEmpty()) {
                (grace ? pending : sumMissing).add(f.bvid + "@" + f.day);
            } else {
                sumDays.addAll(mdDates);
                if (!doneDates.isEmpty()) {
                    distillDays.addAll(doneDates);
                } else {
                    (grace ? pending : distillMissing).add(f.bvid + "@md" + mdDates.first());
                }
            }
            if (row == null) {
                bilibiliVideoService.save(newRow(f.bvid, mid, index.get(f.bvid), pub, expected));
                inserted++;
            } else if (!LEASED.contains(row.getStep()) && STEP_ORDER.indexOf(expected) > STEP_ORDER.indexOf(
                row.getStep())) {
                /* 文件事实领先 DB(Python 补跑处理过/当晚 sum 漏 curl/蒸馏无回写): 推进, 失败计数归零 */
                row.setStep(expected);
                row.setStatus(0);
                row.setRetryCount(0);
                bilibiliVideoService.updateById(row);
                advanced++;
            }
        }
        List<String> partial = files.values().stream().filter(f -> !f.full).map(f -> f.bvid + "@" + f.day).toList();
        List<String> orphanDistill = distilled.stream().filter(d -> !distillDays.contains(d)).map(LocalDate::toString)
            .toList();
        /* 10/17: 用户确认跳过的视频(如付费充电视频, remark 含"跳过")不算失败, 单列 INFO, 不再每轮报 FAILED */
        List<String> skipped = db.values().stream()
            .filter(v -> v.getRetryCount() != null && v.getRetryCount() >= 3 && v.getRemark() != null && v.getRemark().contains("跳过"))
            .map(v -> v.getBvid() + "(" + v.getStep() + ")").toList();
        List<String> failed = db.values().stream().filter(v -> v.getRetryCount() != null && v.getRetryCount() >= 3)
            .map(v -> v.getBvid() + "(" + v.getStep() + ")").filter(s -> !skipped.contains(s)).toList();

        List<ReconcileResult> rows = new ArrayList<>();
        rows.add(reconcileResultService.of(batchNo, BIZ, up, "results", "全部产物齐",
            "齐 " + files.values().stream().filter(f -> f.full).count() + " 条/" + resultDays.size() + " 天, 半成品 "
                + partial.size(), partial.isEmpty() ? "OK" : "WARN",
            partial.isEmpty() ? null : "半成品(按 10/11 立法应整夹删后重跑): " + head(partial)));
        rows.add(reconcileResultService.of(batchNo, BIZ, up, "sum", 0, sumMissing.size(),
            sumMissing.isEmpty() ? "OK" : "MISSING", sumMissing.isEmpty() ? null : "产物齐但 md 无此视频: " + head(sumMissing)));
        rows.add(reconcileResultService.of(batchNo, BIZ, up, "distill", 0, distillMissing.size(),
            distillMissing.isEmpty() ? "OK" : "MISSING",
            distillMissing.isEmpty() ? null : "已 sum 未蒸馏: " + head(distillMissing)));
        rows.add(reconcileResultService.of(batchNo, BIZ, up, "days", "results " + resultDays.size() + " 天",
            "sum " + sumDays.size() + " / distill " + distillDays.size() + " 天",
            sumMissing.isEmpty() && distillMissing.isEmpty() ? "OK" : "MISSING",
            (pending.isEmpty() ? "" : "当晚待办(未过 " + GRACE_HOURS + "h): " + head(pending) + "; ")
                + "天数按 md 挂载日计, 周末/假期稿可能并到交易日 md, 故可小于 results 天数"));
        rows.add(reconcileResultService.of(batchNo, BIZ, up, "orphan_distill", 0, orphanDistill.size(),
            orphanDistill.isEmpty() ? "OK" : "WARN",
            orphanDistill.isEmpty() ? null : "distill 账本有但无齐产物视频对应的日子: " + head(orphanDistill)));
        rows.add(reconcileResultService.of(batchNo, BIZ, up, "db_sync", "DB=文件事实", "补登记 " + inserted + " / 推进 " + advanced,
            inserted + advanced > 0 ? "FIXED" : "OK", null));
        rows.add(reconcileResultService.of(batchNo, BIZ, up, "db_failed", 0, failed.size(), failed.isEmpty() ? "OK" : "FAILED",
            failed.isEmpty() ? null : "重试 ≥3 次停住: " + head(failed)));
        if (!skipped.isEmpty()) {
            rows.add(reconcileResultService.of(batchNo, BIZ, up, "db_skipped", 0, skipped.size(), "OK",
                "用户确认跳过: " + head(skipped)));
        }
        return rows;
    }

    @Override
    public String enqueueBackfill(String up, LocalDate from, LocalDate to, int max) throws Exception {
        JsonNode cfg = readUps().path(up);
        if (cfg.isMissingNode()) {
            throw new BusinessException("ups.json 无此 UP: " + up);
        }
        String mid = cfg.path("mid").asText();
        Map<String, VideoFiles> files = scanResults(mid);
        List<JsonNode> todo = readIndex(cfg).values().stream()
            .sorted((a, b) -> Long.compare(b.path("pubdate").asLong(), a.path("pubdate").asLong())).toList();
        int inserted = 0;
        int skipped = 0;
        for (JsonNode v : todo) {
            if (inserted >= max) {
                break;
            }
            String bvid = v.path("bvid").asText();
            LocalDateTime pub = publishTimeOf(v, null);
            LocalDate day = pub.toLocalDate();
            if ((from != null && day.isBefore(from)) || (to != null && day.isAfter(to))) {
                continue;
            }
            VideoFiles f = files.get(bvid);
            if ((f != null && f.full) || bilibiliVideoService.existsAnyByBvid(bvid)) {
                skipped++;
                continue;
            }
            bilibiliVideoService.save(newRow(bvid, mid, v, pub, "NEW"));
            inserted++;
        }
        return "补跑登记 " + up + ": 插 NEW " + inserted + " 条(origin=BACKFILL), 已有/产物已齐跳过 " + skipped;
    }

    @Override
    public String midOf(String up) throws Exception {
        String mid = readUps().path(up).path("mid").asText();
        if (mid.isEmpty()) {
            throw new BusinessException("ups.json 无此 UP: " + up);
        }
        return mid;
    }

    private BilibiliVideo newRow(String bvid, String mid, JsonNode idx, LocalDateTime pub, String step) {
        BilibiliVideo v = new BilibiliVideo();
        v.setBvid(bvid);
        v.setAuthorMid(mid);
        v.setTitle(idx == null ? null : idx.path("title").asText(null));
        v.setPublishTime(pub);
        v.setDuration(idx == null || !idx.hasNonNull("duration") ? null : idx.path("duration").asInt());
        v.setUrl("https://www.bilibili.com/video/" + bvid);
        v.setStep(step);
        v.setOrigin(IBilibiliVideoService.ORIGIN_BACKFILL);
        return v;
    }

    /**
     * 发布时间: 索引 pubdate(秒) 优先, 没有就用 results 目录日 00:00
     *
     * @author sichu huang
     * @param idx idx
     * @param day day
     * @since 2026/10/12
     * @return java.time.LocalDateTime
     **/
    private LocalDateTime publishTimeOf(JsonNode idx, LocalDate day) {
        if (idx != null && idx.path("pubdate").asLong() > 0) {
            return LocalDateTime.ofInstant(Instant.ofEpochSecond(idx.path("pubdate").asLong()), CN);
        }
        if (day == null) {
            throw new BusinessException("索引行无 pubdate: " + idx);
        }
        return day.atStartOfDay();
    }

    private JsonNode readUps() throws Exception {
        Path p = Paths.get(projectConfig.getRootDir(), "scripts", "backfill_bilibili", "ups.json");
        return JsonUtils.objectMapper.readTree(p.toFile());
    }

    private Map<String, JsonNode> readIndex(JsonNode cfg) throws Exception {
        Path p = Paths.get(projectConfig.getRootDir(), "scripts", "backfill_bilibili", cfg.path("index").asText());
        Map<String, JsonNode> out = new LinkedHashMap<>();
        if (Files.exists(p)) {
            for (JsonNode v : JsonUtils.objectMapper.readTree(p.toFile())) {
                out.put(v.path("bvid").asText(), v);
            }
        }
        return out;
    }

    private Set<LocalDate> readDistilled(JsonNode cfg) throws Exception {
        Path p = Paths.get(projectConfig.getRootDir(), "scripts", "backfill_bilibili",
            cfg.path("distill_state").asText("distill_state.json"));
        Set<LocalDate> out = new TreeSet<>();
        if (Files.exists(p)) {
            for (JsonNode d : JsonUtils.objectMapper.readTree(p.toFile()).path("done")) {
                out.add(LocalDate.parse(d.asText()));
            }
        }
        return out;
    }

    /**
     * 扫全部 md(md/yyyySq/yyyy-MM-dd.md), 建 bvid → 出现过的 md 日
     *
     * @author sichu huang
     * @since 2026/10/12
     * @return java.util.Map<java.lang.String, java.util.TreeSet<java.time.LocalDate>>
     **/
    private Map<String, TreeSet<LocalDate>> scanMd() throws Exception {
        Map<String, TreeSet<LocalDate>> out = new HashMap<>();
        try (Stream<Path> s = Files.walk(Paths.get(projectConfig.getMarkdown().getRootDir()), 2)) {
            for (Path p : s.filter(Files::isRegularFile).toList()) {
                Matcher name = MD_NAME.matcher(p.getFileName().toString());
                if (!name.matches()) {
                    continue;
                }
                LocalDate d = LocalDate.parse(name.group(1));
                Matcher m = BVID_IN_MD.matcher(Files.readString(p, StandardCharsets.UTF_8));
                while (m.find()) {
                    out.computeIfAbsent(m.group(1), k -> new TreeSet<>()).add(d);
                }
            }
        }
        return out;
    }

    /**
     * 扫 results/bilibili/&lt;mid&gt;/&lt;yyyy.MM.dd&gt;/: 有 txt 且 vision.json 含 pages/vlm=齐(同 Java advanceToVisionDone + Python scan_done 口径), 只有部分产物=半成品
     *
     * @author sichu huang
     * @param mid mid
     * @since 2026/10/12
     * @return java.util.Map<java.lang.String, cn.sichu.bilibili.service.impl.BilibiliReconcileServiceImpl.VideoFiles>
     **/
    private Map<String, VideoFiles> scanResults(String mid) throws Exception {
        Path base = Paths.get(projectConfig.getFile().getResult().getRootDir(), "bilibili", mid);
        Map<String, VideoFiles> out = new LinkedHashMap<>();
        if (!Files.exists(base)) {
            return out;
        }
        try (Stream<Path> days = Files.list(base)) {
            for (Path dayDir : days.filter(Files::isDirectory).sorted().toList()) {
                LocalDate day;
                try {
                    day = LocalDate.parse(dayDir.getFileName().toString(), DateTimeUtils.YYYYMMDD_DOT);
                } catch (Exception e) {
                    continue;
                }
                Set<String> bvids = new HashSet<>();
                try (Stream<Path> fs = Files.list(dayDir)) {
                    fs.map(p -> p.getFileName().toString()).filter(n -> n.startsWith("BV"))
                        .forEach(n -> bvids.add(n.substring(0, Math.min(12, n.length()))));
                }
                for (String bvid : bvids) {
                    Path txt = dayDir.resolve(bvid + ".txt");
                    Path vision = dayDir.resolve(bvid + ".vision.json");
                    boolean full = false;
                    if (Files.exists(txt) && Files.exists(vision)) {
                        String vj = Files.readString(vision, StandardCharsets.UTF_8);
                        full = vj.contains("\"pages\"") || vj.contains("\"vlm\"");
                    }
                    out.put(bvid, new VideoFiles(bvid, day, full));
                }
            }
        }
        return out;
    }

    private String head(List<String> list) {
        return list.stream().limit(LIST_MAX).collect(Collectors.joining(",")) + (list.size() > LIST_MAX ?
            " …共 " + list.size() : "");
    }

    /**
     * 单视频产物状态
     *
     * @author sichu huang
     * @since 2026/10/12
     **/
    private record VideoFiles(String bvid, LocalDate day, boolean full) {
    }
}
