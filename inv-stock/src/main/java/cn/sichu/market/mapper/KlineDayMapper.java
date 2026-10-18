package cn.sichu.market.mapper;

import cn.sichu.market.entity.KlineDay;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.time.LocalDate;
import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
@Mapper
public interface KlineDayMapper extends BaseMapper<KlineDay> {

    /**
     * 物理删除某交易日全部日线(幂等重导: 先删后插)
     * 不能用 MyBatis-Plus 的 delete(), 全局开了逻辑删除, delete() 只会 UPDATE is_deleted=1, 重跑会越积越多
     *
     * @author sichu huang
     * @param tradeDate tradeDate
     * @since 2026/10/11
     * @return int
     **/
    int physicalDeleteByTradeDate(@Param("tradeDate") LocalDate tradeDate);

    /**
     * 批量插入; create_by/create_time 由 service 赋值
     *
     * @author sichu huang
     * @param list list
     * @since 2026/10/11
     * @return int
     **/
    int insertBatch(@Param("list") List<KlineDay> list);

    /**
     * 物理删除某标的某日期区间的日线(历史回补幂等重导: 先删后插, 区间=回补文件的首尾日期)
     * 不能用 MyBatis-Plus 的 delete(), 全局开了逻辑删除, delete() 只会 UPDATE is_deleted=1, 重跑会越积越多
     *
     * @author sichu huang
     * @param symbol symbol
     * @param fromDate fromDate
     * @param toDate toDate
     * @since 2026/10/11
     * @return int
     **/
    int physicalDeleteBySymbolAndRange(@Param("symbol") String symbol, @Param("fromDate") LocalDate fromDate,
        @Param("toDate") LocalDate toDate);
}
