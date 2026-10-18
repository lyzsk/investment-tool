package cn.sichu.market.mapper;

import cn.sichu.market.entity.AdjustmentFactor;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
@Mapper
public interface AdjustmentFactorMapper extends BaseMapper<AdjustmentFactor> {

    /**
     * 物理删除某标的全部复权因子(历史回补幂等重导: 先删后插)
     * 不能用 MyBatis-Plus 的 delete(), 全局开了逻辑删除, delete() 只会 UPDATE is_deleted=1, 重跑会越积越多
     *
     * @author sichu huang
     * @param symbol symbol
     * @since 2026/10/11
     * @return int
     **/
    int physicalDeleteBySymbol(@Param("symbol") String symbol);

    /**
     * 批量插入; create_by/create_time 由 service 赋值
     *
     * @author sichu huang
     * @param list list
     * @since 2026/10/11
     * @return int
     **/
    int insertBatch(@Param("list") List<AdjustmentFactor> list);
}
