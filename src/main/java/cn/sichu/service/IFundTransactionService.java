package cn.sichu.service;

import cn.sichu.entity.FundTransaction;

import java.io.IOException;
import java.text.ParseException;
import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IFundTransactionService {
    /**
     * @param code
     * @param applicationDate
     * @param share
     * @param type
     * @author sichu huang
     * @date 2024/03/11
     **/
    // public void insertFundRedemptionTransactionByConditions(String code, Date applicationDate, String share,
    //     Integer type) throws IOException;

    /**
     * @return java.util.List<cn.sichu.entity.FundTransaction>
     * @author sichu huang
     * @date 2024/03/09
     **/
    public List<FundTransaction> selectAllFundTransactions();

    /**
     * @param fundTransaction
     * @author sichu huang
     * @date 2024/03/09
     **/
    public void insertFundTransaction(FundTransaction fundTransaction);

    /**
     * @param code
     * @param applicationDate
     * @param amount
     * @param type
     * @param tradingPlatform
     * @author sichu huang
     * @date 2024/03/10
     **/
    public void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, String amount,
        Integer type, String tradingPlatform) throws ParseException, IOException;

    /**
     * @param date
     * @author sichu huang
     * @date 2024/03/16
     **/
    public void updateNavAndShareForFundPurchaseTransaction(String date) throws ParseException;
}
