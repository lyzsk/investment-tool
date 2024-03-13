package cn.sichu.service.impl;

import cn.sichu.entity.FundPurchaseFeeRate;
import cn.sichu.mapper.FundPurchaseFeeRateMapper;
import cn.sichu.service.IFundPurchaseFeeRateService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/13
 **/
@Service
public class IFundPurchaseFeeRateServiceImpl implements IFundPurchaseFeeRateService {
    @Autowired
    private FundPurchaseFeeRateMapper fundPurchaseFeeRateMapper;

    /**
     * @param code
     * @param tradingPlatform
     * @return java.util.List<cn.sichu.entity.FundPurchaseFeeRate>
     * @author sichu huang
     * @date 2024/03/13
     **/
    @Override
    public List<FundPurchaseFeeRate> selectFundPurchaseFeeRateByConditions(String code, String tradingPlatform) {
        FundPurchaseFeeRate fundPurchaseFeeRate = new FundPurchaseFeeRate();
        fundPurchaseFeeRate.setCode(code);
        fundPurchaseFeeRate.setTradingPlatform(tradingPlatform);
        return fundPurchaseFeeRateMapper.selectFundPurchaseFeeRateByConditions(fundPurchaseFeeRate);
    }
}
