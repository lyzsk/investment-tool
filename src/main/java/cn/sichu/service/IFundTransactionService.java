package cn.sichu.service;

import cn.sichu.entity.FundPurchaseTransaction;
import cn.sichu.entity.FundRedemptionTransaction;
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
     * @param fundPurchaseTransaction fundPurchaseTransaction
     * @author sichu huang
     * @date 2024/03/21
     **/
    void insertFundTransactionByFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);

    /**
     * @param fundRedemptionTransaction fundRedemptionTransaction
     * @author sichu huang
     * @date 2024/03/24
     **/
    void insertFundTransactionByFundRedemptionTransaction(FundRedemptionTransaction fundRedemptionTransaction);

    /**
     * @param code            code
     * @param applicationDate applicationDate
     * @param amount          amount
     * @param tradingPlatform tradingPlatform
     * @author sichu huang
     * @date 2024/03/10
     **/
    void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, BigDecimal amount, String tradingPlatform)
        throws ParseException, IOException;

    /**
     * @param code            code
     * @param applicationDate applicationDate
     * @param share           share
     * @param tradingPlatform tradingPlatform
     * @author sichu huang
     * @date 2024/03/24
     **/
    void insertFundRedemptionTransactionByConditions(String code, Date applicationDate, BigDecimal share, String tradingPlatform)
        throws ParseException, IOException;

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/20
     **/
    void insertFundPositionByFundPurchaseTransaction(FundPurchaseTransaction purchaseTransaction) throws ParseException, IOException;

    /**
     * @return java.util.List<cn.sichu.entity.FundTransaction>
     * @author sichu huang
     * @date 2024/03/09
     **/
    List<FundTransaction> selectAllFundTransactions();

    /**
     * @author sichu huang
     * @date 2024/03/16
     **/
    void updateNavAndShareForFundPurchaseTransaction();

    /**
     * @author sichu huang
     * @date 2024/03/18
     **/
    void updateNavAndShareForFundTransaction();

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
    void updateStatusForTransactionInTransit(Date date) throws ParseException, IOException;

}
