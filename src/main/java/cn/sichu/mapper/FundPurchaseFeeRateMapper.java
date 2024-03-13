package cn.sichu.mapper;

import cn.sichu.entity.FundPurchaseFeeRate;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
@Mapper
public interface FundPurchaseFeeRateMapper {
    public List<FundPurchaseFeeRate> selectFundPurchaseFeeRateByConditions(FundPurchaseFeeRate fundPurchaseFeeRate);
}
