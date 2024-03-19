package cn.sichu.service;

import cn.sichu.entity.FundPurchaseTransaction;

import java.text.ParseException;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
public interface IFundPositionService {

    /**
     * @param purchaseTransactions purchaseTransactions
     * @author sichu huang
     * @date 2024/03/19
     **/
    void insertFundPosition(List<FundPurchaseTransaction> purchaseTransactions) throws ParseException;

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/19
     **/
    void updateHeldDaysAndUpdateDateForFundPosition(FundPurchaseTransaction purchaseTransaction) throws ParseException;
}
