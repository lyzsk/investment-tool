package cn.sichu.market.service;

import cn.sichu.market.entity.StockIndustry;

import java.time.LocalDate;
import java.util.Collection;
import java.util.Map;

/**
 * 个股行业时点查询(只读): 申万优先, 申万当日无归属时退证监会
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
public interface IStockIndustryService {

    /**
     * 某股某日的行业归属; 申万(SW)优先, 没有则证监会(CSRC); 都没有返回 null
     *
     * @author sichu huang
     * @param symbol symbol
     * @param date date
     * @since 2026/10/16
     * @return cn.sichu.market.entity.StockIndustry
     **/
    StockIndustry getIndustry(String symbol, LocalDate date);

    /**
     * 批量: 一批股某日的行业归属(同 getIndustry 口径); 查不到的 symbol 不在结果里
     *
     * @author sichu huang
     * @param symbols symbols
     * @param date date
     * @since 2026/10/16
     * @return java.util.Map&lt;java.lang.String,cn.sichu.market.entity.StockIndustry&gt;
     **/
    Map<String, StockIndustry> mapIndustry(Collection<String> symbols, LocalDate date);
}
