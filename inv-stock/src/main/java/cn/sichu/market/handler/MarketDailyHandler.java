package cn.sichu.market.handler;

import cn.sichu.market.service.IMarketImportService;
import cn.sichu.market.service.IMarketPipelineService;
import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import utils.DateTimeUtils;
import utils.StringUtils;
import utils.TradingDayUtils;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
@Slf4j
@Component("marketDailyHandler")
@RequiredArgsConstructor
public class MarketDailyHandler implements JobHandler {
    private final ProjectConfig projectConfig;
    private final IMarketImportService marketImportService;
    private final IMarketPipelineService marketPipelineService;

    /**
     * params 为空: 当日(非交易日跳过)整条流水线 日线采集 → 除权检测 → 日线+因子入库 → 关注集+分时采集 → 入库(见 IMarketPipelineService.runDay)
     * params=yyyy-MM-dd: 只入库该日已采好的文件(补导/手动重跑), 有分时文件则一并入库
     *
     * @author sichu huang
     * @param params params
     * @since 2026/10/11
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        if (StringUtils.isNotEmpty(params)) {
            LocalDate d = LocalDate.parse(params.trim(), DateTimeUtils.YYYY_MM_DD);
            String result = marketImportService.importDaily(d);
            if (Files.exists(Paths.get(projectConfig.getMarket().getOutputDir(),
                d.format(DateTimeUtils.YYYY_MM_DD), "DONE_kline_minute"))) {
                result += "; " + marketImportService.importMinute(d);
            }
            return result;
        }
        LocalDate today = LocalDate.now();
        if (!TradingDayUtils.isTradingDay(today)) {
            return "非交易日跳过 " + today;
        }
        return marketPipelineService.runDay(today);
    }
}
