package cn.sichu.paper.handler;

import cn.sichu.paper.service.IChainIngestService;
import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import utils.ProcessUtils;
import utils.TradingDayUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/10/06 15:13
 */
@Component("paperReviewHandler")
@RequiredArgsConstructor
@Slf4j
public class PaperReviewHandler implements JobHandler {
    private static final long TIMEOUT_MIN = 40;
    private final ProjectConfig projectConfig;
    private final IChainIngestService chainIngestService;

    @Override
    public String execute(String params) throws Exception {
        LocalDate today = LocalDate.now();
        if (!TradingDayUtils.isTradingDay(today)) {
            return "非交易日跳过 " + today;
        }
        String dateArg = today.format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        Path runDir =
            Paths.get(projectConfig.getRootDir(), "results", "taoge_chain", "live-" + dateArg);
        if (!Files.isRegularFile(runDir.resolve("06_verdict.md"))) {
            return "当日无 06_verdict.md(链未跑完), 跳过 07 复盘: " + runDir;
        }
        List<String> cmd = new ArrayList<>();
        cmd.add(python().toString());
        cmd.add(
            Paths.get(projectConfig.getRootDir(), "scripts", "taoge-chain", "run_chain.py")
                .toString());
        cmd.add("--review");
        cmd.add("--date");
        cmd.add(dateArg);
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        /* ProcessUtils 独立线程读输出, 超时真生效(原先读到 EOF 才 waitFor, 子进程挂住则超时永不触发) */
        LocalDateTime startedAt = LocalDateTime.now();
        ProcessUtils.Result res = ProcessUtils.run(pb, TIMEOUT_MIN);
        /* §5.5 链路入库(07 复盘时段), 失败只记日志 */
        try {
            log.info(chainIngestService.ingest("taoge", "LIVE", today, "review", res.timedOut() ? -1 : res.exit(),
                startedAt, LocalDateTime.now()));
        } catch (Exception e) {
            log.warn("链入库失败 review: {}", e.getMessage());
        }
        String tail = res.tail();
        if (res.timedOut()) {
            throw new BusinessException(
                "run_chain.py --review 超时 " + TIMEOUT_MIN + "min" + "(进程树已杀)");
        }
        if (res.exit() != 0) {
            throw new BusinessException("--review 失败 exit=" + res.exit() + ", 输出尾部: " + tail);
        }
        return "paper 07 复盘完成 " + today;
    }

    /**
     * venv 优先, 无则 PATH python(与 BilibiliVideoServiceImpl 同款)
     */
    private Path python() {
        Path venvPy =
            Paths.get(projectConfig.getRootDir(), "scripts", "venv", "Scripts", "python.exe");
        return Files.isRegularFile(venvPy) ? venvPy : Paths.get("python");
    }
}
