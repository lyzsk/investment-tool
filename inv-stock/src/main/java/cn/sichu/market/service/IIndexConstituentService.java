package cn.sichu.market.service;

import cn.sichu.market.entity.IndexConstituent;

import java.time.LocalDate;
import java.util.List;

/**
 * 指数成分时点查询(只读): 一律按日期 D 查, 不用"今天的成分"看过去
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
public interface IIndexConstituentService {

    /**
     * 某日某指数的成分快照
     *
     * @param indexSymbol 指数 symbol, 如 sh000300 / csi932000
     * @param date        查询日 D
     * @param members     D 当日成分(按 conCode 升序)
     * @param complete    true=D &gt;= coverage.pitFrom, 成分完整; false=只是当前存活者子集(缺 D 之后被剔除的样本), 研究慎用
     * @param note        complete=false 时的说明
     * @author sichu huang
     * @since 2026/10/16
     **/
    record ConstituentSnapshot(String indexSymbol, LocalDate date, boolean complete, String note,
                               List<IndexConstituent> members) {
    }

    /**
     * 按日期查指数成分; 没有该指数覆盖记录或 D 早于最早记录日抛 BusinessException
     *
     * @author sichu huang
     * @param indexSymbol indexSymbol
     * @param date date
     * @since 2026/10/16
     * @return cn.sichu.market.service.IIndexConstituentService.ConstituentSnapshot
     **/
    ConstituentSnapshot listConstituents(String indexSymbol, LocalDate date);

    /**
     * 按日期查个股当时属于哪些指数(只返回本表覆盖的指数; 未达 pitFrom 的指数也会返回, 自行看 coverage)
     *
     * @author sichu huang
     * @param conSymbol conSymbol
     * @param date date
     * @since 2026/10/16
     * @return java.util.List&lt;cn.sichu.market.entity.IndexConstituent&gt;
     **/
    List<IndexConstituent> listIndexesOf(String conSymbol, LocalDate date);
}
