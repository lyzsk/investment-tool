package cn.sichu.kline.service.impl;

import cn.sichu.kline.service.IKlineInboxService;
import cn.sichu.system.config.ProjectConfig;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import result.ResultCode;
import utils.CollectionUtils;
import utils.DateTimeUtils;
import utils.ProcessUtils;
import utils.StringUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Set;
import java.util.stream.Stream;

/**
 * @author sichu huang
 * @since 2026/10/25
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class KlineInboxServiceImpl implements IKlineInboxService {
    /* 收件箱一轮最长: OCR 约 5 秒一张(限 2 线程) + 每只票统计 1~2 分钟 */
    private static final long TIMEOUT_MIN = 30;
    private static final Set<String> ALLOWED_EXT = Set.of("jpg", "jpeg", "png", "webp");
    private final ProjectConfig projectConfig;

    private Path inboxDir() {
        return Paths.get(projectConfig.getFile().getDownload().getRootDir(), "kline");
    }

    @Override
    public String upload(List<MultipartFile> files, String date) {
        if (CollectionUtils.isEmpty(files)) {
            throw new BusinessException(ResultCode.FILE_EMPTY);
        }
        String day = StringUtils.isEmpty(date) ? LocalDate.now().format(DateTimeUtils.YYYYMMDD_DOT) : date.trim();
        try {
            LocalDate.parse(day, DateTimeUtils.YYYYMMDD_DOT);
        } catch (DateTimeParseException e) {
            throw new BusinessException("date 格式要 yyyy.MM.dd: " + day);
        }
        Path dir = inboxDir().resolve(day);
        int saved = 0, skipped = 0;
        try {
            Files.createDirectories(dir);
            for (MultipartFile file : files) {
                if (file.isEmpty()) {
                    continue;
                }
                String name = Paths.get(StringUtils.isEmpty(file.getOriginalFilename()) ? "img.jpg" : file.getOriginalFilename()).getFileName().toString();
                String ext = name.contains(".") ? name.substring(name.lastIndexOf('.') + 1).toLowerCase() : "";
                if (!ALLOWED_EXT.contains(ext)) {
                    skipped++;
                    continue;
                }
                Path dst = dir.resolve(name);
                if (Files.exists(dst)) {
                    /* 同名同大小 = 同一张图重复上传, 跳过; 同名不同大小加序号 */
                    if (Files.size(dst) == file.getSize()) {
                        skipped++;
                        continue;
                    }
                    String stem = name.substring(0, name.lastIndexOf('.'));
                    int k = 2;
                    while (Files.exists(dst)) {
                        dst = dir.resolve(stem + "_" + k++ + "." + ext);
                    }
                }
                Files.copy(file.getInputStream(), dst, StandardCopyOption.REPLACE_EXISTING);
                saved++;
            }
        } catch (Exception e) {
            log.error("K 线截图保存失败 {}: {}", dir, e.getMessage());
            throw new BusinessException("K 线截图保存失败: " + e.getMessage());
        }
        return String.format("存入 %d/跳过 %d → %s", saved, skipped, dir);
    }

    @Override
    public String process(String date, boolean force) throws Exception {
        String rootDir = projectConfig.getRootDir();
        List<String> cmd = new ArrayList<>(
            Arrays.asList(ProcessUtils.condaPython(rootDir), "-X", "utf8",
                Paths.get(rootDir, "scripts", "kline_study", "kline_inbox.py").toString(), "--all"));
        if (StringUtils.isNotEmpty(date)) {
            cmd.addAll(Arrays.asList("--day", date.trim()));
        }
        if (force) {
            cmd.add("--force");
        }
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(rootDir).toFile());
        /* 本地 OCR 吃 CPU: 限 2 线程(用户 10/24: 打游戏时别抢资源) */
        pb.environment().put("OMP_NUM_THREADS", "2");
        return ProcessUtils.runChecked(pb, TIMEOUT_MIN, "kline_inbox.py");
    }

    @Override
    public String cleanupLocalImages(int retentionDays) {
        Path klineDir = inboxDir();
        if (!Files.isDirectory(klineDir)) {
            return "kline 截图目录不存在, 跳过";
        }
        LocalDate cutoff = LocalDate.now().minusDays(retentionDays);
        int removed = 0, failed = 0;
        try (Stream<Path> dirs = Files.list(klineDir)) {
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
                    log.error("kline 截图目录删除失败 {}: {}", dayDir, e.getMessage());
                    failed++;
                }
            }
        } catch (Exception e) {
            return "kline 截图清理异常: " + e.getMessage();
        }
        return String.format("kline截图清理 %d 个日期目录/失败 %d", removed, failed);
    }
}
