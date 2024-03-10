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
    private FundInformationMapper fundInformationMapper;

    /**
     * @param code 基金编码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public List<FundInformation> selectFundTransactionProcessByCode(String code) {
        return fundInformationMapper.selectFundTransactionProcessByCode(code);
    }

    /**
     * @param code 基金编码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public List<FundInformation> selectFundShortNameByCode(String code) {
        return fundInformationMapper.selectFundShortNameByCode(code);
    }

    /**
     * @param code 基金编码
     * @return java.util.List<cn.sichu.entity.FundInformation>
     * @author sichu huang
     * @date 2024/03/10
     **/
    @Override
    public List<FundInformation> selectFundPurchaseFeeRateByCode(String code) {
        return fundInformationMapper.selectFundPurchaseFeeRateByCode(code);
    }
}
