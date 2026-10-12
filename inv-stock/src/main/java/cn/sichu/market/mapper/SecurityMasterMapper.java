package cn.sichu.market.mapper;

import cn.sichu.market.entity.SecurityMaster;
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
public interface SecurityMasterMapper extends BaseMapper<SecurityMaster> {

    /**
     * 批量插入(新标的); 自定义 XML 不走 MyMetaObjectHandler 自动填充, create_by/create_time 由 service 赋值
     *
     * @author sichu huang
     * @param list list
     * @since 2026/10/11
     * @return int
     **/
    int insertBatch(@Param("list") List<SecurityMaster> list);
}
