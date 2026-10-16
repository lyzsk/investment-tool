package cn.sichu.market.handler;

import cn.sichu.market.service.ILhbImportService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.DateTimeUtils;
import utils.StringUtils;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/15
 **/
@Component("lhbImportHandler")
@RequiredArgsConstructor
public class LhbImportHandler implements JobHandler {
    /* 每日任务回看交易日数: 接住晚到/18:00 前临时版被重抓的日子 */
    private static final int LOOKBACK_DAYS = 5;
    private final ILhbImportService lhbImportService;

    /**
     * 龙虎榜入行情库(lhb_stock / lhb_seat), 只读 fetch_lhb.mjs 已落盘的 downloads/lhb/, 本任务不联网(采集归 check md 的 lhb 步)
     * params 为空: 最近 5 个交易日完整的逐日重导(幂等), 未就绪的跳过; params=yyyy-MM-dd: 只导该日; params=ALL: 历史全量(手动 runOnce)
     *
     * @author sichu huang
     * @param params params
     * @since 2026/10/15
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        if (StringUtils.isEmpty(params) || StringUtils.isEmpty(params.trim())) {
            return lhbImportService.importRecent(LOOKBACK_DAYS);
        }
        String p = params.trim();
        if ("ALL".equalsIgnoreCase(p)) {
            return lhbImportService.importAll();
        }
        return lhbImportService.importDay(LocalDate.parse(p, DateTimeUtils.YYYY_MM_DD));
    }
}
