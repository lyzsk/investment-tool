package cn.sichu.enums;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
public enum FundTransactionType {
    PURCHASE(0, "买入"), REDEMPTION(1, "赎回"), DIVIDEND(2, "分红");

    private final Integer code;
    private final String description;

    FundTransactionType(Integer code, String description) {
        this.code = code;
        this.description = description;
    }

    public Integer getCode() {
        return code;
    }

    public String getDescription() {
        return description;
    }
}
