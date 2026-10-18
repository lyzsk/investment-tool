package cn.sichu.market.service;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
public interface IMarketImportService {

    /**
     * 读 downloads/market/&lt;tradeDate&gt;/ 下采集脚本产出的 jsonl 入库(须先有 DONE_security / DONE_kline_day)
     * security_master: 按 symbol 有则更新(只更新变化字段)/无则插入, 不删(退市股保留)
     * kline_day: 该交易日先物理删除再批量插入(幂等, 重跑结果一致)
     * adjustment_factor: 有 DONE_factor 时, adjustment_factor.jsonl 里的标的按标的整体替换(除权日刷新)
     *
     * @author sichu huang
     * @param tradeDate tradeDate
     * @since 2026/10/11
     * @return java.lang.String
     **/
    String importDaily(LocalDate tradeDate) throws Exception;

    /**
     * 读 downloads/market/&lt;tradeDate&gt;/ 下 watchlist_info.jsonl + kline_minute.jsonl 入库(须先有 DONE_watchlist / DONE_kline_minute)
     * 两表都按交易日先物理删除再批量插入(幂等)
     *
     * @author sichu huang
     * @param tradeDate tradeDate
     * @since 2026/10/11
     * @return java.lang.String
     **/
    String importMinute(LocalDate tradeDate) throws Exception;

    /**
     * 读 downloads/market/&lt;北京日期&gt;/global_security.jsonl + global_kline.jsonl 入库(须先有 DONE_global, 第 4 段外围)
     * security_master 有则更新/无则插入; kline_day 按 symbol+当地交易日先物理删除再插入(幂等)
     *
     * @author sichu huang
     * @param day 采集当天(北京日期, 即目录名)
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String importGlobal(LocalDate day) throws Exception;

    /**
     * 读 downloads/market/&lt;tradeDate&gt;/call_auction_&lt;phase&gt;.jsonl 入库(须先有 DONE_auction_&lt;phase&gt;), 该日该段先物理删除再批量插入(幂等)
     *
     * @author sichu huang
     * @param tradeDate tradeDate
     * @param phase OPEN / CLOSE
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String importAuction(LocalDate tradeDate, String phase) throws Exception;

    /**
     * 读 downloads/market/history/ 下历史回补产物(backfill_history.py, 10/12 起腾讯日线+新浪因子)入库(须先有 DONE_basic)
     * security_master: 补上市/退市日, 退市股等缺失标的补行; kline_day: 每只票按回补文件首尾日期区间先删后插;
     * adjustment_factor: 每只票先删后插; 每只票一个事务, 中途失败重跑即可(幂等)
     *
     * @author sichu huang
     * @since 2026/10/11
     * @return java.lang.String
     **/
    String importHistory() throws Exception;
}
