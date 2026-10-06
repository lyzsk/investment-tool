package cn.sichu.bilibili.service.impl;

import cn.sichu.bilibili.entity.BilibiliVideo;
import cn.sichu.bilibili.mapper.BilibiliVideoMapper;
import cn.sichu.bilibili.service.IBilibiliVideoService;
import cn.sichu.system.config.ProjectConfig;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import utils.DateTimeUtils;
import utils.ExceptionUtils;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/09/26 21:26
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BilibiliVideoServiceImpl extends ServiceImpl<BilibiliVideoMapper, BilibiliVideo>
    implements IBilibiliVideoService {
    /* 7B bf16 需 ~15GB 显存 */
    private static final long MIN_VRAM_BYTES = 15_000_000_000L;
    private final ProjectConfig projectConfig;

    @Override
    public BilibiliVideo getByBvid(String bvid) {
        return getOne(new LambdaQueryWrapper<BilibiliVideo>().eq(BilibiliVideo::getBvid, bvid),
            false);
    }

    @Override
    public List<BilibiliVideo> listByStep(String step, int maxRetry) {
        return baseMapper.selectByStep(step, maxRetry);
    }

    @Override
    public String downloadPendingVideos(int maxRetry) {
        int downloaded = 0, failed = 0;
        for (BilibiliVideo v : baseMapper.selectByStep("NEW", maxRetry)) {
            try {
                downloadOne(v);
                downloaded++;
            } catch (Exception e) {
                  /* 失败: step 原地不动(保留死在哪个阶段), status=1, retry_count+1,
                     下个周期 listByStep 自动重捞, >=3 沉底 */
                String reason = e instanceof BusinessException ? e.getMessage() :
                    ExceptionUtils.getStacktrace(e, 480);
                markFail(v, reason);
                failed++;
            }
        }
        return String.format("下载成功 %d/失败 %d", downloaded, failed);
    }

    @Override
    public String processPendingVideos(int maxRetry) {
        /* 0=无venv 1=仅CPU 2=全配 */
        int cap = detectCapability();
        if (cap == 0) {
            return "未检测到 scripts/venv, 处理全部跳过(下载不受影响; 安装见 README Quick Start: "
                + "pip install -r scripts/requirements-taoge.txt)";
        }
        int processed = 0, failed = 0, partial = 0;
        for (BilibiliVideo v : baseMapper.selectByStep("DOWNLOADED", maxRetry)) {
            try {
                if (processOne(v, cap == 2)) {
                    processed++;
                } else {
                    partial++;
                }
            } catch (Exception e) {
                String reason = e instanceof BusinessException ? e.getMessage() :
                    ExceptionUtils.getStacktrace(e, 480);
                markFail(v, reason);
                failed++;
            }
        }
        return String.format("处理成功 %d/失败 %d%s", processed, failed,
            cap == 1 ? "/仅CPU部分完成 " + partial + "(无GPU, 视觉留待有显卡的机器)" : "");
    }

    /**
     * 环境能力判定: 0=无 venv, 1=仅 CPU(venv 在但 torch 无 CUDA 或显存<15G), 2=全配
     * torch import ~10s, 每次 job 执行只探一次
     */
    private int detectCapability() {
        Path venvPy = venvPython();
        if (venvPy == null) {
            return 0;
        }
        try {
            ProcessBuilder pb = new ProcessBuilder(venvPy.toString(), "-c",
                "import torch;print(torch.cuda.is_available() "
                    + "and torch.cuda.get_device_properties(0).total_memory >= " + MIN_VRAM_BYTES
                    + ")");
            pb.redirectErrorStream(true);
            Process proc = pb.start();
            String out =
                new String(proc.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
            if (!proc.waitFor(3, TimeUnit.MINUTES)) {
                proc.destroyForcibly();
                return 1;
            }
            return (proc.exitValue() == 0 && out.endsWith("True")) ? 2 : 1;
        } catch (Exception e) {
            /* venv 在但探测失败 → 保守按仅 CPU(还能跑 ASR) */
            return 1;
        }
    }

    private Path venvPython() {
        Path venvPy = Paths.get(projectConfig.getRootDir())
            .resolve(Paths.get("scripts", "venv", "Scripts", "python.exe"));
        return Files.isRegularFile(venvPy) ? venvPy : null;
    }

    /**
     * 下载单个视频的全部产物到 downloads/bilibili/<作者mid>/<发布日 yyyy.MM.dd>/:
     * mp4(画面流, 视觉管线用) + m4a(音轨, ASR用) + json(view API 原始响应全文), 一次 node 调用全拿
     * (脚本内一次 playurl 同时取 dash.audio+dash.video, 幂等: 已存在的产物跳过只补缺)。
     * 目录约定(TODO 2.9)由本方法显式传 --out 实现, 脚本只认"给目录我存哪";
     * mid 作目录段=表是通用 B站索引(不限桃哥), 路径由 DB 行的 author_mid 驱动。
     * 产物路径不入库(2026-09-29 用户定: 命名约定可从 bvid/author_mid/publish_time 派生,
     * 磁盘是唯一事实, source_files 列已删); 回溯=拿 url/bvid 重跑 mjs。
     * 成功: step→DOWNLOADED, retry_count 归零
     *
     * @param v BilibiliVideo
     * @author sichu huang
     * @since 2026/09/27 01:30:39
     */
    private void downloadOne(BilibiliVideo v) throws Exception {
        String day = DateTimeUtils.getDotDateStr(v.getPublishTime());
        Path outDir = Paths.get(projectConfig.getFile().getDownload().getRootDir(), "bilibili",
            v.getAuthorMid(), day);
        Files.createDirectories(outDir);
        runNode("bilibili/fetch_bilibili.mjs", "--bvid", v.getBvid(), "--out", outDir.toString());
        v.setStep("DOWNLOADED");
        v.setStatus(0);
        v.setRetryCount(0);
        v.setRemark(null);
        updateById(v);
    }

    /**
     * 处理单个视频(DOWNLOADED → VISION_DONE): 原料在 downloads/(可删), 结果在 results/(永久)
     *
     * @param fullVision true=全配(含 7B 视觉); false=仅 CPU, 只跑 asr+correct, step 不动等视觉
     * @return true=推进到 VISION_DONE; false=仅完成 ASR 部分(txt 已出, 视觉留待)
     */
    private boolean processOne(BilibiliVideo v, boolean fullVision) throws Exception {
        String day = DateTimeUtils.getDotDateStr(v.getPublishTime());
        Path rawDir = Paths.get(projectConfig.getFile().getDownload().getRootDir(), "bilibili",
            v.getAuthorMid(), day);
        Path outDir = Paths.get(projectConfig.getFile().getResult().getRootDir(), "bilibili",
            v.getAuthorMid(), day);
        Path txt = outDir.resolve(v.getBvid() + ".txt");
        Path visionJson = outDir.resolve(v.getBvid() + ".vision.json");
        /* 产物已齐(孤儿 python 跑完/人工补跑) → 不起进程直接推进 */
        if (Files.isRegularFile(txt) && hasPages(visionJson)) {
            advanceToVisionDone(v);
            return true;
        }
        if (fullVision) {
            runPython("bilibili/process_video.py", "--bvid", v.getBvid(), "--mp4",
                rawDir.resolve(v.getBvid() + ".mp4").toString(), "--m4a",
                rawDir.resolve(v.getBvid() + ".m4a").toString(), "--out", outDir.toString());
            /* 成败判据=产物校验不是 exit 0: txt(纠错后) + vision.json 含 pages 段 */
            if (!Files.isRegularFile(txt) || !hasPages(visionJson)) {
                throw new BusinessException(
                    "process_video.py 产物不全: 缺 txt 或 vision.json 无 pages 段");
            }
            advanceToVisionDone(v);
            return true;
        }
        /* 仅 CPU: 只跑 asr+correct(txt 照出), 视觉等全配机器; txt 已有则本轮无事可做 */
        if (!Files.isRegularFile(txt)) {
            runPython("bilibili/process_video.py", "--bvid", v.getBvid(), "--m4a",
                rawDir.resolve(v.getBvid() + ".m4a").toString(), "--out", outDir.toString(),
                "--stage", "asr,correct");
        }
        return false;
    }

    private void advanceToVisionDone(BilibiliVideo v) {
        v.setStep("VISION_DONE");
        v.setStatus(0);
        v.setRetryCount(0);
        v.setRemark(null);
        updateById(v);
    }

    private boolean hasPages(Path visionJson) throws Exception {
        return Files.isRegularFile(visionJson) && Files.readString(visionJson,
            StandardCharsets.UTF_8).contains("\"pages\"");
    }

    /**
     * 跑 scripts/ 下的 python 脚本: 优先 scripts/venv/Scripts/python.exe(无则 PATH python),
     * 超时 60min(视觉 7B 单视频 ~15-20min, 留余量)
     */
    private void runPython(String scriptName, String... args) throws Exception {
        Path root = Paths.get(projectConfig.getRootDir());
        Path venvPy = venvPython();
        String pythonExe = venvPy != null ? venvPy.toString() : "python";
        List<String> cmd = new ArrayList<>();
        cmd.add(pythonExe);
        cmd.add(root.resolve("scripts").resolve(scriptName).toString());
        cmd.addAll(Arrays.asList(args));
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(root.toFile());
        pb.redirectErrorStream(true);
        String tail = waitAndTail(pb.start(), 60, scriptName);
        if (tail != null) {
            throw new BusinessException(tail);
        }
    }

    private void runNode(String scriptName, String... args) throws Exception {
        Path script = Paths.get(projectConfig.getRootDir(), "scripts", scriptName);
        List<String> cmd = new ArrayList<>();
        cmd.add("node");
        cmd.add(script.toString());
        cmd.addAll(Arrays.asList(args));
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        pb.redirectErrorStream(true);
        String tail = waitAndTail(pb.start(), 5, scriptName);
        if (tail != null) {
            throw new BusinessException(tail);
        }
    }

    /**
     * 等子进程结束并收输出尾部(失败原因用): stderr 合并进 stdout 防两流缓冲死锁由调用方保证,
     * UTF-8 读(Windows 控制台默认 GBK), 超时强杀
     *
     * @return 失败原因(超时/非零退出), 成功返回 null
     */
    private String waitAndTail(Process proc, long timeoutMin, String label) throws Exception {
        StringBuilder tail = new StringBuilder();
        try (BufferedReader br = new BufferedReader(
            new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                tail.append(line).append('\n');
                if (tail.length() > 2000) {
                    tail.delete(0, tail.length() - 2000);
                }
            }
        }
        if (!proc.waitFor(timeoutMin, TimeUnit.MINUTES)) {
            proc.destroyForcibly();
            return label + " 超时" + timeoutMin + "min强杀";
        }
        if (proc.exitValue() != 0) {
            return label + " exit=" + proc.exitValue() + ", 输出尾部: " + tail;
        }
        return null;
    }

    @Override
    public String cleanupPhysicalFiles(int retentionDays) {
        LocalDateTime threshold = LocalDateTime.now().minusDays(retentionDays);
        /* @TableLogic 自动带 is_deleted=0。
           2026-09-29 用户定: source_files 列已删, 路径从 bvid/author_mid/publish_time 按命名约定派生
           (磁盘是唯一事实, 顺带消除"写库路径硬编码 vs 下载目录配置"双真相分叉隐患);
           幂等=三件套全不在则视为已清理, 跳过且不动 remark */
        List<BilibiliVideo> list = lambdaQuery().eq(BilibiliVideo::getStep, "SUMMARIZED")
            .lt(BilibiliVideo::getUpdateTime, threshold).list();
        int cleaned = 0, failed = 0, already = 0;
        for (BilibiliVideo v : list) {
            try {
                String day = DateTimeUtils.getDotDateStr(v.getPublishTime());
                Path dir = Paths.get(projectConfig.getFile().getDownload().getRootDir(), "bilibili",
                    v.getAuthorMid(), day);
                boolean anyDeleted = false;
                for (String ext : new String[] {".mp4", ".m4a", ".json"}) {
                    anyDeleted |= Files.deleteIfExists(dir.resolve(v.getBvid() + ext));
                }
                if (!anyDeleted) {
                    already++;
                    continue;
                }
                v.setRemark("原料物理删除于 " + LocalDate.now());
                updateById(v);
                cleaned++;
            } catch (Exception e) {
                log.error("物理删除失败 bvid={}: {}", v.getBvid(), e.getMessage());
                failed++;
            }
        }
        return String.format("bilibili原料清理 %d/失败 %d/已是空 %d", cleaned, failed, already);
    }

    private void markFail(BilibiliVideo v, String reason) {
        v.setStatus(1);
        v.setRetryCount((v.getRetryCount() == null ? 0 : v.getRetryCount()) + 1);
        if (reason != null && reason.length() > 480) {
            reason = reason.substring(reason.length() - 480);
        }
        v.setRemark(reason);
        updateById(v);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String markSummarized(List<String> bvids) {
        int advanced = 0, skipped = 0, notFound = 0;
        for (String bvid : bvids) {
            BilibiliVideo v = getByBvid(bvid);
            if (v == null) {
                notFound++;
                continue;
            }
            if (!"VISION_DONE".equals(v.getStep())) {
                skipped++;
                continue;
            }
            v.setStep("SUMMARIZED");
            updateById(v);
            advanced++;
        }
        return String.format("推进SUMMARIZED %d/跳过 %d(非VISION_DONE)/未找到 %d", advanced,
            skipped, notFound);
    }
}
