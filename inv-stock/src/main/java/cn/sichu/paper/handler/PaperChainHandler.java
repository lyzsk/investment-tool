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
 * paper 模拟盘 A 定时链: 按 slot 触发决策链(claude -p 无头)。
 * 契约=skills/taoge-skill/workflows/chain.md 与 skills/cb-skill/workflows/chain.md; 驱动器=scripts/taoge-chain/run_taoge_chain.py。
 * sys_job: job_handler_name=paperChainHandler, job_handler_param=slot(HHMM, 如 0915/0927/1230)、
 *   cb:slot(如 cb:0915=转债链, 10/4 盲区修复⑦)或 review。
 * 出口约定: 0=链完成; 3=ESCALATE_FULL_CHAIN(市况变, 子链升级, 一期只告警靠下个 slot 兜); 其他=失败抛异常。
 *
 * @author sichu huang
 * @since 2026/10/02
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
            throw new BusinessException("paperChainHandler 需要 param=slot(HHMM)、cb:slot 或 review");
        }
        // cb:HHMM 前缀=转债链(驱动器 --skill cb); 无前缀=taoge 链
        String skill = "taoge";
        if (slot.startsWith("cb:")) {
            skill = "cb";
            slot = slot.substring(3);
        }
        String date = today.format(DateTimeFormatter.BASIC_ISO_DATE);   // yyyyMMdd
        Path driver = Paths.get(projectConfig.getRootDir(), "scripts", "taoge-chain", "run_taoge_chain.py");
        ProcessBuilder pb = "review".equals(slot)
            ? new ProcessBuilder(python(), driver.toString(), "--skill", skill, "--review", "--date", date)
            : new ProcessBuilder(python(), driver.toString(), "--skill", skill, "--slot", slot, "--date", date);
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
            throw new BusinessException("run_taoge_chain.py 超时 " + TIMEOUT_MIN + "min slot=" + slot);
        }
        int exit = proc.exitValue();
        if (exit == 3) {
            log.warn("paper 链 ESCALATE_FULL_CHAIN slot={} (市况变, 一期靠下个 slot 兜底): {}", slot, tail);
            return "ESCALATE_FULL_CHAIN slot=" + slot;
        }
        if (exit != 0) {
            throw new BusinessException("run_taoge_chain.py 失败 skill=" + skill + " slot=" + slot + " exit=" + exit
                + ", 输出尾部: " + tail);
        }
        return "paper 链完成 skill=" + skill + " slot=" + slot;
    }

    private String python() {
        // 附录 B: 先 venv 再 PATH
        Path venv = Paths.get(projectConfig.getRootDir(), "scripts", "venv", "Scripts", "python.exe");
        return Files.exists(venv) ? venv.toString() : "python";
    }
}
