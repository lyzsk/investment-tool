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
     * 1. 插入买入交易表, 如果满足条件: nav和share不为空, 并且status为持仓, 则插入持仓表;
     * <br/>
     * 2. 插入总交易表;
     *
     * @param code            基金代码 (6位)
     * @param applicationDate 交易申请日
     * @param amount          交易金额
     * @param tradingPlatform 交易平台
     * @author sichu huang
     * @date 2024/03/10
     **/
    void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, BigDecimal amount, String tradingPlatform)
        throws ParseException, IOException;

    /**
     * insert into `fund_redemption_transaction` with:
     * <br/>
     * 1.code, 2.application_date, 3.transaction_date, 4.confirmation_date, 5.settlement_date, <b>6.amount(optional),
     * 7.fee(optional), 8.nav(optional),</b> 9.share, 10.trading_platform, 11.status, 12.mark
     * <p/>
     * insert into `fund_transaction` with:
     * <br/>
     * 1.code, 2.application_date, 3.transaction_date, 4.confirmation_date, 5.settlement_date, <b>6.amount(optional),
     * 7.fee(optional), 8.nav(optional),</b> 9.share, 10.trading_platform, 11.status, 12.mark, 13.type
     * <p/>
     * if REDEEMED:
     * <br/>
     * insert into `fund_history_position` with:
     * <br/>
     * 1.code, 2.transaction_date, 3.initiation_date, 4.redemption_date, 5.total_amount, 6.total_purchase_fee,
     * 7.total_redemption_fee, 8.held_share, 9.held_days, 10.mark;
     * <br/>
     * delete from `fund_position`:
     * <br/>
     * 1.code, 2.transaction_date, 3.initiation_date, 4.redemption_date, 5.total_amount, 6.total_purchase_fee,
     * 7.total_redemption_fee, 8.held_share, 9.held_days, 10.mark;
     *
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
    void updateNavAndShareForFundPurchaseTransaction() throws ParseException, IOException;

    /**
     * @author sichu huang
     * @date 2024/03/25
     **/
    void updateNavAndFeeAndAmountForFundRedemptionTransaction() throws ParseException, IOException;

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
