package cn.sichu.market.service;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
public interface IMarketPipelineService {

    /**
     * 某交易日整条行情流水线(每段有 DONE 标记就跳过采集, 入库一律重做=幂等):
     * 日线采集(最近收盘日=collect_daily.mjs 新浪快照; 更早=backfill_history.py --day 腾讯补采) → 除权检测 refresh_factors.py
     * → 日线+因子入库 → 关注集+分时采集 collect_minute.py(通达信逐笔, 往日可补) → 分时入库
     * 同一时刻只允许一条流水线(收盘任务/对账补采/启动补采共用一把锁), 抢不到锁直接报错
     *
     * @author sichu huang
     * @param day day
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String runDay(LocalDate day) throws Exception;

    /**
     * 最近一个已收盘的交易日: 交易日 15:30 后=当天, 否则=上一个交易日
     *
     * @author sichu huang
     * @since 2026/10/12
     * @return java.time.LocalDate
     **/
    LocalDate latestClosedTradingDay();

    /**
     * 行情库对账(第 6 段): 回看 reconcileLookbackDays 个交易日(不早于 reconcileStartDate), 逐日核 kline_day/kline_minute 行数,
     * 缺了就 runDay 补; 开盘竞价错过不可补只记 UNRECOVERABLE; 除权因子校验超期记 WARN; 结果写 reconcile_result, 有问题推 hermes
     *
     * @author sichu huang
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String reconcile() throws Exception;
}
