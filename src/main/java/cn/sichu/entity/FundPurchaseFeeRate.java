package cn.sichu.entity;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
public class FundPurchaseFeeRate {
    private Long id;
    private String code;
    private Long feeRateChangeAmount;
    private String feeRate;
    private String tradingPlatform;

    public FundPurchaseFeeRate() {
    }

    public FundPurchaseFeeRate(Long id, String code, Long feeRateChangeAmount, String feeRate, String tradingPlatform) {
        this.id = id;
        this.code = code;
        this.feeRateChangeAmount = feeRateChangeAmount;
        this.feeRate = feeRate;
        this.tradingPlatform = tradingPlatform;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("id", getId()).append("code", getCode())
            .append("feeRateChangeAmount", getFeeRateChangeAmount()).append("feeRate", getFeeRate())
            .append("tradingPlatform", getTradingPlatform()).toString();
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

    public Long getFeeRateChangeAmount() {
        return feeRateChangeAmount;
    }

    public void setFeeRateChangeAmount(Long feeRateChangeAmount) {
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
}
