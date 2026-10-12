package cn.sichu.market.handler;

import cn.sichu.market.service.IMarketImportService;
import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.DateTimeUtils;
import utils.ProcessUtils;
import utils.StringUtils;
import utils.TradingDayUtils;

import java.nio.file.Paths;
import java.time.LocalDate;
import java.util.Set;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Component("marketAuctionHandler")
@RequiredArgsConstructor
public class MarketAuctionHandler implements JobHandler {
    private static final Set<String> PHASES = Set.of("OPEN", "CLOSE");
    /* 脚本自己等到竞价开始, 采到结束(OPEN 09:15~09:25:40 / CLOSE 14:57~15:00:40), 任务提前 1 分钟触发 */
    private static final long TIMEOUT_MIN = 20;
    private final ProjectConfig projectConfig;
    private final IMarketImportService marketImportService;

    /**
     * 集合竞价采集+入库(第 5 段): params=OPEN(cron 09:14) / CLOSE(cron 14:56); 竞价不可事后补, 失败只能记缺口(对账记 UNRECOVERABLE)
     * params="OPEN yyyy-MM-dd" 形式=只入库该日已采好的文件(补导)
     *
     * @author sichu huang
     * @param params params
     * @since 2026/10/12
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        String[] parts = StringUtils.isEmpty(params) ? new String[0] : params.trim().split("\\s+");
        if (parts.length == 0 || !PHASES.contains(parts[0].toUpperCase())) {
            throw new BusinessException("参数须为 OPEN / CLOSE [yyyy-MM-dd], 实际: " + params);
        }
        String phase = parts[0].toUpperCase();
        if (parts.length > 1) {
            return marketImportService.importAuction(LocalDate.parse(parts[1], DateTimeUtils.YYYY_MM_DD), phase);
        }
        LocalDate today = LocalDate.now();
        if (!TradingDayUtils.isTradingDay(today)) {
            return "非交易日跳过 " + today;
        }
        String rootDir = projectConfig.getRootDir();
        ProcessBuilder pb = new ProcessBuilder(ProcessUtils.venvPython(rootDir), "-X", "utf8",
            Paths.get(rootDir, "scripts", "market", "collect_auction.py").toString(), "--phase", phase, "--date",
            today.format(DateTimeUtils.YYYY_MM_DD));
        pb.directory(Paths.get(rootDir).toFile());
        ProcessUtils.runChecked(pb, TIMEOUT_MIN, "collect_auction.py");
        return marketImportService.importAuction(today, phase);
    }
}
