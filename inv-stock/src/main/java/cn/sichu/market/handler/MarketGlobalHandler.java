package cn.sichu.market.handler;

import cn.sichu.market.service.IMarketImportService;
import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.DateTimeUtils;
import utils.ProcessUtils;
import utils.StringUtils;

import java.nio.file.Paths;
import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Component("marketGlobalHandler")
@RequiredArgsConstructor
public class MarketGlobalHandler implements JobHandler {
    private final ProjectConfig projectConfig;
    private final IMarketImportService marketImportService;

    /**
     * 外围市场收盘快照(第 4 段, cron 每天 08:30, 不看 A 股交易日: 美股周五夜盘要在周六早上收): collect_global.py → 入库
     * params=yyyy-MM-dd: 只入库该日(北京日期目录)已采好的文件
     *
     * @author sichu huang
     * @param params params
     * @since 2026/10/12
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        if (StringUtils.isNotEmpty(params)) {
            return marketImportService.importGlobal(LocalDate.parse(params.trim(), DateTimeUtils.YYYY_MM_DD));
        }
        String rootDir = projectConfig.getRootDir();
        ProcessBuilder pb = new ProcessBuilder(ProcessUtils.venvPython(rootDir), "-X", "utf8",
            Paths.get(rootDir, "scripts", "market", "collect_global.py").toString());
        pb.directory(Paths.get(rootDir).toFile());
        ProcessUtils.runChecked(pb, projectConfig.getMarket().getCollectTimeoutMin(), "collect_global.py");
        return marketImportService.importGlobal(LocalDate.now());
    }
}
