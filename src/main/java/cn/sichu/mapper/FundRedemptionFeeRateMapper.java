package cn.sichu.mapper;

import cn.sichu.entity.FundRedemptionFeeRate;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
@Mapper
public interface FundRedemptionFeeRateMapper {
    public List<FundRedemptionFeeRate> selectRedemptionFeeRateByConditions(@Param("code") String code,
        @Param("tradingPlatform") String tradingPlatform);
}
