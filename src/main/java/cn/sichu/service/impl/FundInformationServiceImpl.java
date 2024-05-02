package cn.sichu.service.impl;

import cn.sichu.entity.FundInformation;
import cn.sichu.mapper.FundInformationMapper;
import cn.sichu.service.IFundInformationService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Service
public class FundInformationServiceImpl implements IFundInformationService {
    @Autowired
    FundInformationMapper fundInformationMapper;

    /**
     * @param code 基金代码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public List<FundInformation> selectFundPurchaseTransactionProcessByCode(String code) {
        return fundInformationMapper.selectFundPurchaseTransactionProcessByCode(code);
    }

    /**
     * @param code 基金代码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/24
     **/
    @Override
    public List<FundInformation> selectFundRedemptionTransactionProcessByCode(String code) {
        return fundInformationMapper.selectFundRedemptionTransactionProcessByCode(code);
    }

}
