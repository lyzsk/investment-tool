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
     * @param fundTransaction fundTransaction
     * @author sichu huang
     * @date 2024/03/09
     **/
    void insertFundTransaction(FundTransaction fundTransaction);

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/18
     **/
    void insertFundPurchaseTransaction(FundPurchaseTransaction purchaseTransaction) throws ParseException;

    /**
     * @param code            code
     * @param applicationDate applicationDate
     * @param amount          amount
     * @param tradingPlatform tradingPlatform
     * @author sichu huang
     * @date 2024/03/10
     **/
    void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, BigDecimal amount,
        String tradingPlatform) throws ParseException, IOException;

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/20
     **/
    void insertFundPositionByFundPurchaseTransaction(FundPurchaseTransaction purchaseTransaction) throws ParseException;

    /**
     * @return java.util.List<cn.sichu.entity.FundTransaction>
     * @author sichu huang
     * @date 2024/03/09
     **/
    List<FundTransaction> selectAllFundTransactions();

    /**
     * @return java.util.List<cn.sichu.entity.FundPurchaseTransaction>
     * @author sichu huang
     * @date 2024/03/17
     **/
    List<FundPurchaseTransaction> selectAllFundPurchaseTransactions();

    /**
     * @param code   code
     * @param status status
     * @return java.util.List<cn.sichu.entity.FundPurchaseTransaction>
     * @author sichu huang
     * @date 2024/03/19
     **/
    List<FundPurchaseTransaction> selectAllFundPurchaseTransactionsByConditions(String code, Integer status);

    /**
     * @param status status
     * @return java.util.List<cn.sichu.entity.FundPurchaseTransaction>
     * @author sichu huang
     * @date 2024/03/19
     **/
    List<FundPurchaseTransaction> selectAllFundPurchaseTransactionsByStatus(Integer status);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/16
     **/
    void updateNavAndShareForFundPurchaseTransaction(Date date);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/18
     **/
    void updateNavAndShareForFundTransaction(Date date);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/16
     **/
    void updateStatusForFundTransaction(Date date);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/18
     **/
    void updateStatusForFundPurchaseTransaction(Date date);

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/19
     **/
    void updateHeldDaysAndUpdateDateForFundPosition(FundPurchaseTransaction purchaseTransaction) throws ParseException;

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    void updateHeldDaysAndUpdateDateForFundPosition(Date date) throws ParseException;

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    void updateStatusForTransactionInTransit(Date date) throws ParseException;

}
