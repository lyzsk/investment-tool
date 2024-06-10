package cn.sichu.enums;

/**
 * @author sichu huang
 * @date 2024/06/10
 **/
public enum GoldTransactionType {
    PURCHASE(0, "购买"), REDEMPTION(1, "赎回");

    private final Integer code;
    private final String description;

    GoldTransactionType(Integer code, String description) {
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
