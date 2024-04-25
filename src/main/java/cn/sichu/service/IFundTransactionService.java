package cn.sichu.service;

import java.io.IOException;
import java.math.BigDecimal;
import java.text.ParseException;
import java.util.Date;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IFundTransactionService {

    /**
     * <b>INSERT into `fund_transaction`</b> with:
     * <br/>
     * 1.id, 2.code, 3.application_date, 4.transaction_date, 5.confirmation_date, 6.settlement_date,
     * 7.amount, 8.fee, 9.nav, 10.share, 11.dividend_amount_per_share, 12.trading_platform,
     * 13.status, 14.mark, 15.type
     * <br/>
     * <b>INSERT into `fund_position`</b>  with:
     * 1.id, 2.code, 3.transaction_date, 4.initiation_date, 5.redemption_date, 6.total_principal_amount,
     * 7.total_amount, 8.total_purchase_fee, 9.total_redemption_fee, 10.held_share, 11.held_days, 12.update_date,
     * 13.status, 14.mark
     * <p/>
     * 对于 `fund_transaction`, <b>1.id</b> 通过mapper自增; <b>9.nav, 10.share</b> 可能为null, <b>11.dividend_amount_per_share, 14.mark</b> 必为null;
     * <br/>
     * 共15个字段, 10个字段<b>必填</b>, 2个字段<b>选填</b>, 3个字段不填;
     * <p/>
     * 对于 `fund_position`, 仅当 fund_transaction.status = HELD 时, 才会插入,
     * 其中 <b>1.id</b> 通过mapper自增; <b>5.redemption_date, 9.total_redemption_fee, 14.mark</b> 必为null
     * <br/>
     * 共14个字段, 10个字段<b>必填</b>, 4个字段不填;
     * <p/>
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
     * <b>INSERT into `fund_transaction`</b> with:
     * <br/>
     * 1.id, 2.code, 3.application_date, 4.transaction_date, 5.confirmation_date, 6.settlement_date,
     * 7.amount, 8.fee, 9.nav, 10.share, 11.dividend_amount_per_share, 12.trading_platform,
     * 13.status, 14.mark, 15.type
     * <br/>
     * <b>UPDATE `fund_position`</b> with:
     * 1.id, 2.code, 3.transaction_date, 4.initiation_date, 5.redemption_date, 6.total_principal_amount,
     * 7.total_amount, 8.total_purchase_fee, 9.total_redemption_fee, 10.held_share, 11.held_days, 12.update_date,
     * 13.status, 14.mark
     * <p/>
     * 对于 `fund_transaction`, <b>1.id</b> 通过mapper自增; <b>7.amount, 8.fee, 9.nav</b> 可能为null, <b>11.dividend_amount_per_share</b> 必为null
     * <br/>
     * 共15个字段, 10个字段<b>必填</b>, 3个字段<b>选填</b>, 1个字段<b>不填</b>;
     * <p/>
     * 对于 `fund_position`, 无论 fund_transaction.status = REDEMPTION_IN_TRANSIT/REDEEMED 时, 都会执行,
     * 其中 <b>5.redemption_date, 13.status, 14.mark</b> 必更新;
     * 仅当currentDate > transaction.confirmation_date 时, 更新 <b>7.total_amount, 9.total_redemption_fee, 11.held_days, 12.update_date</b>,
     * <br/>
     * 共14个字段, 2个字段<b>必更新</b>, 4个字段<b>可能更新</b>, 8个字段<b>不更新</b>
     * <p/>
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
     * <b>INSERT into `fund_transaction`</b> with:
     * <br/>
     * 1.id, 2.code, 3.application_date, 4.transaction_date, 5.confirmation_date, 6.settlement_date,
     * 7.amount, 8.fee, 9.nav, 10.share, 11.dividend_amount_per_share, 12.trading_platform,
     * 13.status, 14.mark, 15.type
     * <p/>
     * 对于 `fund_transaction`, <b>1.id</b> 通过mapper自增; <b>7.amount, 10.share, 11.dividend_amount_per_share</b>必填;
     * <b>8.fee, 9.nav, 14.mark</b> 必为null;
     * <br/>
     * 共15个字段, 11个字段<b>必填</b>, 4个字段<b>不填</b>;
     *
     * @param code                   基金代码 (6位)
     * @param applicationDate        交易申请日
     * @param dividendAmountPerShare 每股现金分红金额
     * @param tradingPlatform        交易平台
     * @author sichu huang
     * @date 2024/04/07
     **/
    void dividendFund(String code, Date applicationDate, BigDecimal dividendAmountPerShare, String tradingPlatform);

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
