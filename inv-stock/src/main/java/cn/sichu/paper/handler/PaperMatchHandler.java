package cn.sichu.paper.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.ProcessUtils;
import utils.TradingDayUtils;

import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalTime;

/**
 * @author sichu huang
 * @since 2026/10/02 15:12
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
        boolean inWindow =
            (!t.isBefore(LocalTime.of(9, 30)) && !t.isAfter(LocalTime.of(11, 30))) || (
                !t.isBefore(LocalTime.of(13, 0)) && !t.isAfter(LocalTime.of(15, 0)));
        if (!inWindow) {
            return "非撮合时段跳过 " + t;
        }
        ProcessBuilder pb = new ProcessBuilder("node",
            Paths.get(projectConfig.getRootDir(), "scripts", "dfcf", "paper", "matcher.mjs")
                .toString(), "--once");
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        /* 10/11: ProcessUtils 独立线程读输出, 超时真生效(原先读到 EOF 才 waitFor, 子进程挂住则超时永不触发) */
        ProcessUtils.Result res = ProcessUtils.run(pb, TIMEOUT_MIN);
        String tail = res.tail();
        if (res.timedOut()) {
            throw new BusinessException(
                "matcher.mjs --once 超时 " + TIMEOUT_MIN + "min" + "(进程树已杀)");
        }
        if (res.exit() != 0) {
            throw new BusinessException(
                "matcher.mjs --once 失败 exit=" + res.exit() + ", 输出尾部: " + tail);
        }
        return "撮合完成 " + t;
    }
}
