package cn.sichu.entity;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
public class FundPurchaseFeeRate {
    private Long id;
    private String code;
    private String feeRateChangeAmount;
    private String feeRate;
    private String tradingPlatform;

    public FundPurchaseFeeRate() {
    }

    public FundPurchaseFeeRate(Long id, String code, String feeRateChangeAmount, String feeRate,
        String tradingPlatform) {
        this.id = id;
        this.code = code;
        this.feeRateChangeAmount = feeRateChangeAmount;
        this.feeRate = feeRate;
        this.tradingPlatform = tradingPlatform;
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getFeeRateChangeAmount() {
        return feeRateChangeAmount;
    }

    public void setFeeRateChangeAmount(String feeRateChangeAmount) {
        this.feeRateChangeAmount = feeRateChangeAmount;
    }

    public String getFeeRate() {
        return feeRate;
    }

    public void setFeeRate(String feeRate) {
        this.feeRate = feeRate;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }

    @Override
    public String toString() {
        return "FundPurchaseFeeRate{" + "id=" + id + ", code='" + code + '\'' + ", feeRateChangeAmount='"
            + feeRateChangeAmount + '\'' + ", feeRate='" + feeRate + '\'' + ", tradingPlatform='" + tradingPlatform
            + '\'' + '}';
    }
}
