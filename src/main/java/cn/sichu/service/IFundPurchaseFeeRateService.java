package cn.sichu.service;

import cn.sichu.entity.FundPurchaseFeeRate;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/13
 **/
public interface IFundPurchaseFeeRateService {
    /**
     * @param code
     * @param tradingPlatform
     * @return java.util.List<cn.sichu.entity.FundPurchaseFeeRate>
     * @author sichu huang
     * @date 2024/03/13
     **/
    public List<FundPurchaseFeeRate> selectFundPurchaseFeeRateByConditions(String code, String tradingPlatform);
}
