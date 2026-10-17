package cn.sichu.market.mapper;

import cn.sichu.market.entity.KlineMinute;
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
public interface KlineMinuteMapper extends BaseMapper<KlineMinute> {

    /**
     * 物理删除某交易日全部分时(幂等重导: 先删后插; 按分区键 trade_date 删, 只扫当年分区)
     * 不能用 MyBatis-Plus 的 delete(), 全局开了逻辑删除, delete() 只会 UPDATE is_deleted=1, 重跑会越积越多
     *
     * @param tradeDate tradeDate
     * @return int
     * @author sichu huang
     * @since 2026/10/11
     **/
    int physicalDeleteByTradeDate(@Param("tradeDate") LocalDate tradeDate);

    /**
     * 批量插入; create_by/create_time 由 service 赋值
     *
     * @param list list
     * @return int
     * @author sichu huang
     * @since 2026/10/11
     **/
    int insertBatch(@Param("list") List<KlineMinute> list);

    /**
     * 某交易日分时覆盖的不同 symbol 数(对账按覆盖率判, 健壮性 H1)
     *
     * @param tradeDate
     * @return long
     * @author sichu huang
     * @since 2026/10/17
     */
    long countDistinctSymbol(@Param("tradeDate") LocalDate tradeDate);
}
