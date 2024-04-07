package cn.sichu.enums;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
public enum FundTransactionStatus {
    PURCHASE_IN_TRANSIT(0, "买入在途"), HELD(1, "持仓"), REDEMPTION_IN_TRANSIT(2, "赎回在途"), PARTIALLY_REDEEMED(3, "未全额赎回"), REDEEMED(4,
        "已赎回"), CASH_DIVIDEND(5, "现金分红");

    private final Integer code;
    private final String description;

    FundTransactionStatus(Integer code, String decription) {
        this.code = code;
        this.description = decription;
    }

    public Integer getCode() {
        return code;
    }

    public String getDescription() {
        return description;
    }
}
