package cn.sichu.service;

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
     * insert in to `fund_transaction` with:
     * <br/>
     * 1.id, 2.code, 3.application_date, 4.transaction_date, 5.confirmation_date, 6.settlement_date,
     * 7.amount, 8.fee, 9.nav, 10.share, 11.dividend_amount_per_share, 12.trading_platform,
     * 13.status, 14.mark, 15.type
     * <p/>
     * 对于purchase交易, <b>1.id</b> 通过mapper自增; <b>9.nav, 10.share</b> 可能为null, <b>11.dividend_amount_per_share, 14.mark</b> 必为null
     * <br/>
     * i. 当nav更新后, <b>9.nav, 10.share</b> 更新 (每日20:00-24:00, 每小时尝试更新一次)
     * <br/>
     * ii. 当purchase状态为HELD, 则 insert `fund_position`, 可以不按时间顺序, 但注意要以 redemption transaction(14.mark) 为分界
     *
     * @param code            基金代码 (6位)
     * @param applicationDate 交易申请日
     * @param amount          交易金额
     * @param tradingPlatform 交易平台
     * @author sichu huang
     * @date 2024/03/10
     **/
    void purchaseFund(String code, Date applicationDate, BigDecimal amount, String tradingPlatform) throws ParseException, IOException;

    /**
     * insert into `fund_transaction` with:
     * <br/>
     * 1.id, 2.code, 3.application_date, 4.transaction_date, 5.confirmation_date, 6.settlement_date,
     * 7.amount, 8.fee, 9.nav, 10.share, 11.dividend_amount_per_share, 12.trading_platform,
     * 13.status, 14.mark, 15.type
     * <p/>
     * 对于redemption交易, <b>1.id</b> 通过mapper自增; <b>7.amount, 8.fee, 9.nav</b> 可能为null, <b>11.dividend_amount_per_share</b> 必为null
     * <br/>
     * i. 当nav更新后, <b>7.amount, 8.fee, 9.nav</b> 更新 (每日20:00-24:00, 每小时尝试更新一次)
     *
     * @param code            基金代码 (6位)
     * @param applicationDate 交易申请日
     * @param share           交易份额
     * @param tradingPlatform 交易平台
     * @author sichu huang
     * @date 2024/03/24
     **/
    void redeemFund(String code, Date applicationDate, BigDecimal share, String tradingPlatform) throws ParseException, IOException;

    /**
     * @param code                   基金代码 (6位)
     * @param applicationDate        交易申请日
     * @param dividendAmountPerShare 每股现金分红金额
     * @param tradingPlatform        交易平台
     * @author sichu huang
     * @date 2024/04/07
     **/
    void insertFundDividendTransactionByConditions(String code, Date applicationDate, BigDecimal dividendAmountPerShare, String tradingPlatform);

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
     * update 5.total_amount, 8.held_days, 9.update_date for `fund_position`
     *
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    void updateTotalAmountAndHeldDaysAndUpdateDateForFundPosition(Date date) throws ParseException, IOException;

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    void updateStatusForTransactionInTransit(Date date) throws ParseException, IOException;

}
