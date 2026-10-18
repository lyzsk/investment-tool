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
import java.time.format.DateTimeFormatter;

/**
 *
 * @author sichu huang
 * @since 2026/10/02 15:10
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
        /* --date 参数格式 yyyy-MM-dd */
        ProcessBuilder pb = new ProcessBuilder("node",
            Paths.get(projectConfig.getRootDir(), "scripts", "dfcf", "paper", "matcher.mjs")
                .toString(), "--eod", "--date",
            today.format(DateTimeFormatter.ISO_LOCAL_DATE));
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        /* 10/11: ProcessUtils 独立线程读输出, 超时真生效(原先读到 EOF 才 waitFor, 子进程挂住则超时永不触发) */
        ProcessUtils.Result res = ProcessUtils.run(pb, TIMEOUT_MIN);
        String tail = res.tail();
        if (res.timedOut()) {
            throw new BusinessException(
                "matcher.mjs --eod 超时 " + TIMEOUT_MIN + "min" + "(进程树已杀)");
        }
        if (res.exit() != 0) {
            throw new BusinessException(
                "matcher.mjs --eod 失败 exit=" + res.exit() + ", 输出尾部: " + tail);
        }
        return "paper EOD 完成 " + today;
    }
}
