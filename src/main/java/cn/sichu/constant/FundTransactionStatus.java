package cn.sichu.constant;

/**
 * @author sichu huang
 * @date 2024/05/25
 **/
public class FundTransactionStatus {
    /* 买入在途 */
    public static final Integer PURCHASE_IN_TRANSIT = 0;
    /* 持仓 */
    public static final Integer HELD = 1;
    /* 赎回在途 */
    public static final Integer REDEMPTION_IN_TRANSIT = 2;
    /* 部分赎回 */
    public static final Integer PARTIALLY_REDEEMED = 3;
    /* 已全额赎回 */
    public static final Integer REDEEMED = 4;
    /* 现金分红 */
    public static final Integer CASH_DIVIDEND = 5;
}
