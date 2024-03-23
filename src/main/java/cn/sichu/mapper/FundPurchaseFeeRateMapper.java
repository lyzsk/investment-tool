package cn.sichu.mapper;

import cn.sichu.entity.FundPurchaseFeeRate;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
@Mapper
public interface FundPurchaseFeeRateMapper {
    public List<FundPurchaseFeeRate> selectFundPurchaseFeeRateByConditions(@Param("code") String code,
        @Param("tradingPlatform") String tradingPlatform);
}
