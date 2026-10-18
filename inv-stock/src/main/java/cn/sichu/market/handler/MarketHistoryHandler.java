package cn.sichu.market.handler;

import cn.sichu.market.service.IMarketImportService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
@Component("marketHistoryHandler")
@RequiredArgsConstructor
public class MarketHistoryHandler implements JobHandler {
    private final IMarketImportService marketImportService;

    /**
     * 历史回补入库(手动 runOnce): 读 scripts/market/backfill_history.py 产出的 downloads/market/history/ 入库, 幂等可重跑
     * 采集本身(腾讯日线+新浪复权因子一次性回补, 约 5 小时)在 Java 外跑, 本任务只负责入库
     *
     * @author sichu huang
     * @param params params
     * @since 2026/10/11
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        return marketImportService.importHistory();
    }
}
