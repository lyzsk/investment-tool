package cn.sichu.paper.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
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
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/10/02 15:11
 */
@Component("paperChainHandler")
@RequiredArgsConstructor
@Slf4j
public class PaperChainHandler implements JobHandler {
    private static final long TIMEOUT_MIN = 30;   // 附录 B: ProcessBuilder 超时 30min(全七步最坏情况)
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) throws Exception {
        LocalDate today = LocalDate.now();
        if (!TradingDayUtils.isTradingDay(today)) {
            return "非交易日跳过 " + today;
        }
        String slot = params == null ? "" : params.trim();
        if (slot.isEmpty()) {
            throw new BusinessException(
                "paperChainHandler 需要 param=slot(HHMM)、buchitudou0:slot(转债链)或 review");
        }
        // <skill>:HHMM 前缀=选链(10/7 泛化+正名: buchitudou0/qushitiange/lubenyuan, 驱动器 --skill); 无前缀=taoge 链
        String skill = "taoge";
        int ci = slot.indexOf(':');
        if (ci > 0) {
            skill = slot.substring(0, ci);
            slot = slot.substring(ci + 1);
        }
        String date = today.format(DateTimeFormatter.BASIC_ISO_DATE);   // yyyyMMdd
        
        Path driver =
            Paths.get(projectConfig.getRootDir(), "scripts", "taoge-chain", "run_taoge_chain.py");
        ProcessBuilder pb = "review".equals(slot) ?
                new ProcessBuilder(python(), driver.toString(), "--skill", skill, "--review", "--date",
                    date) :
                new ProcessBuilder(python(), driver.toString(), "--skill", skill, "--slot", slot,
                    "--date", date);
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
            throw new BusinessException(
                "run_taoge_chain.py 超时 " + TIMEOUT_MIN + "min slot=" + slot);
        }
        int exit = proc.exitValue();
        if (exit == 3) {
            log.warn("paper 链 ESCALATE_FULL_CHAIN slot={} (市况变, 一期靠下个 slot 兜底): {}",
                slot, tail);
            return "ESCALATE_FULL_CHAIN slot=" + slot;
        }
        if (exit != 0) {
            throw new BusinessException(
                "run_taoge_chain.py 失败 skill=" + skill + " slot=" + slot + " exit=" + exit
                    + ", 输出尾部: " + tail);
        }
        return "paper 链完成 skill=" + skill + " slot=" + slot;
    }

    private String python() {
        // 附录 B: 先 venv 再 PATH
        Path venv =
            Paths.get(projectConfig.getRootDir(), "scripts", "venv", "Scripts", "python.exe");
        return Files.exists(venv) ? venv.toString() : "python";
    }
}
