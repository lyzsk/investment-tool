package cn.sichu.service;

import cn.sichu.entity.FundInformation;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IFundInformationService {
    /**
     * @param code 编码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    public List<FundInformation> selectFundInformationByCode(String code);
}
