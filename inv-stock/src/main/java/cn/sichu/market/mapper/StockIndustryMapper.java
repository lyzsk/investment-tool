package cn.sichu.market.mapper;

import cn.sichu.market.entity.StockIndustry;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 只读(查询走 LambdaQueryWrapper); 写入由 scripts/market/index_constituents.py import --commit 整表重建
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
@Mapper
public interface StockIndustryMapper extends BaseMapper<StockIndustry> {
}
