package cn.sichu.service;

import cn.sichu.entity.FundPurchaseTransaction;
import cn.sichu.entity.FundTransaction;

import java.io.IOException;
import java.math.BigDecimal;
import java.text.ParseException;
import java.util.Date;
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
    public List<FundTransaction> selectAllFundTransactions();

    /**
     * @return java.util.List<cn.sichu.entity.FundPurchaseTransaction>
     * @author sichu huang
     * @date 2024/03/17
     **/
    public List<FundPurchaseTransaction> selectAllFundPurchaseTransactions();

    /**
     * @param fundTransaction fundTransaction
     * @author sichu huang
     * @date 2024/03/09
     **/
    public void insertFundTransaction(FundTransaction fundTransaction);

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/18
     **/
    public void insertFundPurchaseTransaction(FundPurchaseTransaction purchaseTransaction);

    /**
     * @param code            code
     * @param applicationDate applicationDate
     * @param amount          amount
     * @param tradingPlatform tradingPlatform
     * @author sichu huang
     * @date 2024/03/10
     **/
    public void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, BigDecimal amount,
        String tradingPlatform) throws ParseException, IOException;

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/16
     **/
    public void updateNavAndShareForFundPurchaseTransaction(Date date);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/18
     **/
    public void updateNavAndShareForFundTransaction(Date date);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/16
     **/
    public void updateStatusForFundTransaction(Date date);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/18
     **/
    public void updateStatusForFundPurchaseTransaction(Date date);
}
