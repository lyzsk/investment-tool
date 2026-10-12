package cn.sichu.paper.mapper;

import cn.sichu.paper.entity.ChainDecision;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Mapper
public interface ChainDecisionMapper extends BaseMapper<ChainDecision> {

    /**
     * 物理删除这些运行下的行(重新入库幂等: 先删后插)
     * 不能用 MyBatis-Plus 的 delete(), 全局开了逻辑删除, delete() 只会 UPDATE is_deleted=1, 重跑会越积越多
     *
     * @author sichu huang
     * @param ids ids
     * @since 2026/10/12
     * @return int
     **/
    int physicalDeleteByRunIds(@Param("ids") List<Long> ids);
}
