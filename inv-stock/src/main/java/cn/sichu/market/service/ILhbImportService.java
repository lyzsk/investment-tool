package cn.sichu.market.service;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/15
 **/
public interface ILhbImportService {

    /**
     * 读 downloads/lhb/&lt;yyyy.MM.dd&gt;/ 下 fetch_lhb.mjs 落盘的 list.json + detail_&lt;code&gt;.json 入库 lhb_stock / lhb_seat
     * 须"完整": list.json 抓取时刻 ≥ 交易日 18:00(之前抓的是临时版) 且每只上榜票都有 detail 文件, 否则抛 BusinessException
     * 两表该交易日先物理删除再批量插入(一个事务, 幂等)
     *
     * @author sichu huang
     * @param tradeDate tradeDate
     * @since 2026/10/15
     * @return java.lang.String
     **/
    String importDay(LocalDate tradeDate) throws Exception;

    /**
     * 每日任务: 回看最近 lookbackDays 个交易日(含今天, 若今天是交易日), 完整的逐日重导(幂等), 未就绪的跳过并在结果里列出
     * 回看几天是为了接住晚到/重抓的日子(check md 18:00~00:00 轮次抓取, 18:00 前抓的临时版会被重抓覆盖)
     *
     * @author sichu huang
     * @param lookbackDays lookbackDays
     * @since 2026/10/15
     * @return java.lang.String
     **/
    String importRecent(int lookbackDays) throws Exception;

    /**
     * 历史全量: downloads/lhb/ 下全部交易日目录逐日重导(每日一个事务, 单日失败不阻断), 手动 runOnce 用
     *
     * @author sichu huang
     * @since 2026/10/15
     * @return java.lang.String
     **/
    String importAll() throws Exception;
}
