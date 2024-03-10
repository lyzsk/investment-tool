package cn.sichu.service;

import cn.sichu.entity.FundInformation;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IFundInformationService {
    /**
     * @param code 基金编码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    public List<FundInformation> selectFundTransactionProcessByCode(String code);

    /**
     * @param code 基金编码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    public List<FundInformation> selectFundShortNameByCode(String code);

    /**
     * @param code 基金编码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/10
     **/
    public List<FundInformation> selectFundPurchaseFeeRateByCode(String code);
}
