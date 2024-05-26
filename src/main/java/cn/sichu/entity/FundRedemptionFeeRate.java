package cn.sichu.entity;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

/**
 * fund_redemption_rule
 *
 * @author sichu huang
 * @date 2024/03/12
 **/
public class FundRedemptionFeeRate {
    private Long id;
    private String code;
    private Integer feeRateChangeDays;
    private String feeRate;
    private String tradingPlatform;

    public FundRedemptionFeeRate() {
    }

    public FundRedemptionFeeRate(Long id, String code, Integer feeRateChangeDays, String feeRate, String tradingPlatform) {
        this.id = id;
        this.code = code;
        this.feeRateChangeDays = feeRateChangeDays;
        this.feeRate = feeRate;
        this.tradingPlatform = tradingPlatform;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("id", getId()).append("code", getCode())
            .append("feeRateChangeDays", getFeeRateChangeDays()).append("feeRate", getFeeRate()).append("tradingPlatform", getTradingPlatform())
            .toString();
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

    public Integer getFeeRateChangeDays() {
        return feeRateChangeDays;
    }

    public void setFeeRateChangeDays(Integer feeRateChangeDays) {
        this.feeRateChangeDays = feeRateChangeDays;
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
