package cn.sichu.service;

import cn.sichu.entity.FundTransaction;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IFundTransactionService {
    /**
     * @return java.util.List<cn.sichu.entity.FundTransaction>
     * @author sichu huang
     * @date 2024/03/09
     **/
    public List<FundTransaction> selectAllFundTransaction();

    /**
     * @param fundTransaction
     * @author sichu huang
     * @date 2024/03/09
     **/
    public void insertFundTransaction(FundTransaction fundTransaction);
}
