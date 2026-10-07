package cn.sichu.paper.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.TradingDayUtils;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/10/06 15:13
 */
@Component("paperReviewHandler")
@RequiredArgsConstructor
public class PaperReviewHandler implements JobHandler {
    private static final long TIMEOUT_MIN = 40;
    private final ProjectConfig projectConfig;

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
            Paths.get(projectConfig.getRootDir(), "scripts", "taoge-chain", "run_taoge_chain.py")
                .toString());
        cmd.add("--review");
        cmd.add("--date");
        cmd.add(dateArg);
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        pb.redirectErrorStream(true);
        StringBuilder tail = new StringBuilder();
        Process proc = pb.start();
        try (BufferedReader br = new BufferedReader(
            new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                tail.append(line).append('\n');
                if (tail.length() > 4000) {
                    tail.delete(0, tail.length() - 4000);
                }
            }
        }
        if (!proc.waitFor(TIMEOUT_MIN, TimeUnit.MINUTES)) {
            proc.destroyForcibly();
            throw new BusinessException("run_taoge_chain.py --review 超时 " + TIMEOUT_MIN + "min");
        }
        if (proc.exitValue() != 0) {
            throw new BusinessException(
                "--review 失败 exit=" + proc.exitValue() + ", 输出尾部: " + tail);
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
