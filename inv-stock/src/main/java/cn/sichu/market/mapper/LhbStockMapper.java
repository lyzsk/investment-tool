package cn.sichu.market.mapper;

import cn.sichu.market.entity.LhbStock;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.time.LocalDate;
import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/10/15
 **/
@Mapper
public interface LhbStockMapper extends BaseMapper<LhbStock> {

    /**
     * 物理删除某交易日(幂等重导: 先删后插); 全局开了逻辑删除, 不能用 MyBatis-Plus 的 delete()
     *
     * @author sichu huang
     * @param tradeDate tradeDate
     * @since 2026/10/15
     * @return int
     **/
    int physicalDeleteByTradeDate(@Param("tradeDate") LocalDate tradeDate);

    /**
     * 批量插入; create_by/create_time 由 service 赋值
     *
     * @author sichu huang
     * @param list list
     * @since 2026/10/15
     * @return int
     **/
    int insertBatch(@Param("list") List<LhbStock> list);
}
