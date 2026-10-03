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
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.TimeUnit;

/**
 * paper 模拟盘日终: 废单核销→nav 结算→nav_*.csv→state_digest.md(次日 facts 用)。
 * sys_job: job_handler_name=paperEodHandler, 无需 param, cron 建议 "0 5 15 * * ?"(15:05)。
 *
 * @author sichu huang
 * @since 2026/10/02
 */
@Component("paperEodHandler")
@RequiredArgsConstructor
public class PaperEodHandler implements JobHandler {
    private static final long TIMEOUT_MIN = 10;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) throws Exception {
        LocalDate today = LocalDate.now();
        if (!TradingDayUtils.isTradingDay(today)) {
            return "非交易日跳过 " + today;
        }
        ProcessBuilder pb = new ProcessBuilder("node",
            Paths.get(projectConfig.getRootDir(), "scripts", "dfcf", "paper", "matcher.mjs").toString(),
            "--eod", "--date", today.format(DateTimeFormatter.ISO_LOCAL_DATE));   // yyyy-MM-dd
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
            throw new BusinessException("matcher.mjs --eod 超时 " + TIMEOUT_MIN + "min");
        }
        if (proc.exitValue() != 0) {
            throw new BusinessException("matcher.mjs --eod 失败 exit=" + proc.exitValue()
                + ", 输出尾部: " + tail);
        }
        return "paper EOD 完成 " + today;
    }
}
