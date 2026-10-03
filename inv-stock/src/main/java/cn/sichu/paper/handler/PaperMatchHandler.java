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
import java.time.LocalTime;
import java.util.concurrent.TimeUnit;

/**
 * paper 模拟盘盘中撮合: 每分钟一轮(保守成交: 买=现价≤挂价/卖=现价≥挂价, 竞价休止 matcher 内部处理)。
 * sys_job: job_handler_name=paperMatchHandler, 无需 param, cron 建议 "0 * 9-14 * * ?"(窗口由本类代码守门)。
 *
 * @author sichu huang
 * @since 2026/10/02
 */
@Component("paperMatchHandler")
@RequiredArgsConstructor
public class PaperMatchHandler implements JobHandler {
    private static final long TIMEOUT_MIN = 5;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) throws Exception {
        if (!TradingDayUtils.isTradingDay(LocalDate.now())) {
            return "非交易日跳过";
        }
        LocalTime t = LocalTime.now();
        boolean inWindow = (!t.isBefore(LocalTime.of(9, 30)) && !t.isAfter(LocalTime.of(11, 30)))
            || (!t.isBefore(LocalTime.of(13, 0)) && !t.isAfter(LocalTime.of(15, 0)));
        if (!inWindow) {
            return "非撮合时段跳过 " + t;
        }
        ProcessBuilder pb = new ProcessBuilder("node",
            Paths.get(projectConfig.getRootDir(), "scripts", "dfcf", "paper", "matcher.mjs").toString(),
            "--once");
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
            throw new BusinessException("matcher.mjs --once 超时 " + TIMEOUT_MIN + "min");
        }
        if (proc.exitValue() != 0) {
            throw new BusinessException("matcher.mjs --once 失败 exit=" + proc.exitValue()
                + ", 输出尾部: " + tail);
        }
        return "撮合完成 " + t;
    }
}
