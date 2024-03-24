package cn.sichu.service;

import cn.sichu.entity.FundInformation;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IFundInformationService {

    /**
     * @param code 基金代码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    List<FundInformation> selectFundShortNameByCode(String code);

    /**
     * @param code 基金代码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    List<FundInformation> selectFundPurchaseTransactionProcessByCode(String code);

    /**
     * @param code 基金代码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/24
     **/
    List<FundInformation> selectFundRedemptionTransactionProcessByCode(String code);
}
