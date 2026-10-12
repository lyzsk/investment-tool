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

/**
 *
 * @author sichu huang
 * @since 2026/10/02 15:11
 */
@Component("paperChainHandler")
@RequiredArgsConstructor
@Slf4j
public class PaperChainHandler implements JobHandler {
    /* 盘中子链(02/04/06)+review; 10/11 由 30 调整(超时此前从未生效) */
    private static final long TIMEOUT_MIN = 40;
    /* 0915 盘前全链(7 步+全局并发闸排队) */
    private static final long FULL_TIMEOUT_MIN = 180;
    private final ProjectConfig projectConfig;
    private final IChainIngestService chainIngestService;

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
        /* <skill>:HHMM 前缀=选链(10/7 泛化+正名: buchitudou0/qushitiange/lubenyuan, 驱动器 --skill); 无前缀=taoge 链 */
        String skill = "taoge";
        int ci = slot.indexOf(':');
        if (ci > 0) {
            skill = slot.substring(0, ci);
            slot = slot.substring(ci + 1);
        }
        /* yyyyMMdd */
        String date = today.format(DateTimeFormatter.BASIC_ISO_DATE);

        Path driver =
            Paths.get(projectConfig.getRootDir(), "scripts", "taoge-chain", "run_taoge_chain.py");
        ProcessBuilder pb = "review".equals(slot) ?
            new ProcessBuilder(python(), driver.toString(), "--skill", skill, "--review", "--date",
                date) :
            new ProcessBuilder(python(), driver.toString(), "--skill", skill, "--slot", slot,
                "--date", date);
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        /* 10/11: 超时改为真生效(ProcessUtils 独立线程读输出); 0915 盘前全链 7 步+全局并发闸排队, 正常 45-120min,
           给 180min; 盘中子链(02/04/06)与 review 40min。原 30min 一刀切从未生效过, 直接生效会误杀全部全链 */
        long timeoutMin = "0915".equals(slot) ? FULL_TIMEOUT_MIN : TIMEOUT_MIN;
        LocalDateTime startedAt = LocalDateTime.now();
        ProcessUtils.Result res = ProcessUtils.run(pb, timeoutMin);
        ingest(skill, slot, today, res.timedOut() ? -1 : res.exit(), startedAt);
        String tail = res.tail();
        if (res.timedOut()) {
            throw new BusinessException(
                "run_taoge_chain.py 超时 " + timeoutMin + "min(进程树已杀) skill=" + skill
                    + " slot=" + slot + ", 输出尾部: " + tail);
        }
        int exit = res.exit();
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

    /**
     * §5.5 链路入库: 进程一结束就把运行目录解析进 chain_* 表(同目录下个时段会覆盖步骤文件, 必须当场入库); 入库失败只记日志, 不影响任务结果
     *
     * @author sichu huang
     * @param skill skill
     * @param slot slot
     * @param day day
     * @param exit exit
     * @param startedAt startedAt
     * @since 2026/10/12
     **/
    private void ingest(String skill, String slot, LocalDate day, int exit, LocalDateTime startedAt) {
        try {
            log.info(chainIngestService.ingest(skill, "LIVE", day, slot, exit, startedAt, LocalDateTime.now()));
        } catch (Exception e) {
            log.warn("链入库失败 skill={} slot={}: {}", skill, slot, e.getMessage());
        }
    }

    private String python() {
        /* 附录 B: 先 venv 再 PATH */
        Path venv =
            Paths.get(projectConfig.getRootDir(), "scripts", "venv", "Scripts", "python.exe");
        return Files.exists(venv) ? venv.toString() : "python";
    }
}
