package cn.sichu.entity;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

import java.math.BigDecimal;
import java.util.Date;

/**
 * `fund_position`
 * <p>
 * update 2024/04/22: 添加3个字段 redemption_date, total_redemption_fee, mark
 *
 * @author sichu huang
 * @date 2024/03/16
 **/
public class FundPosition {
    private Long id;
    private String code;
    private Date transactionDate;
    private Date initiationDate;
    private Date redemptionDate;
    private BigDecimal totalPrincipalAmount;
    private BigDecimal totalAmount;
    private BigDecimal totalPurchaseFee;
    private BigDecimal totalRedemptionFee;
    private BigDecimal heldShare;
    private Integer heldDays;
    private Date updateDate;
    private String tradingPlatform;
    private Integer status;
    private String mark;

    public FundPosition() {
    }

    public FundPosition(Long id, String code, Date transactionDate, Date initiationDate, Date redemptionDate, BigDecimal totalPrincipalAmount,
        BigDecimal totalAmount, BigDecimal totalPurchaseFee, BigDecimal totalRedemptionFee, BigDecimal heldShare, Integer heldDays,
        Date updateDate, String tradingPlatform, Integer status, String mark) {
        this.id = id;
        this.code = code;
        this.transactionDate = transactionDate;
        this.initiationDate = initiationDate;
        this.redemptionDate = redemptionDate;
        this.totalPrincipalAmount = totalPrincipalAmount;
        this.totalAmount = totalAmount;
        this.totalPurchaseFee = totalPurchaseFee;
        this.totalRedemptionFee = totalRedemptionFee;
        this.heldShare = heldShare;
        this.heldDays = heldDays;
        this.updateDate = updateDate;
        this.tradingPlatform = tradingPlatform;
        this.status = status;
        this.mark = mark;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("id", getId()).append("code", getCode())
            .append("transactionDate", getTransactionDate()).append("initiationDate", getInitiationDate())
            .append("redemptionDate", getRedemptionDate()).append("totalPrincipalAmount", getTotalPrincipalAmount())
            .append("totalAmount", getTotalAmount()).append("totalPurchaseFee", getTotalPurchaseFee())
            .append("totalRedemptionFee", getTotalRedemptionFee()).append("heldShare", getHeldShare()).append("heldDays", getHeldDays())
            .append("updateDate", getUpdateDate()).append("tradingPlatform", getTradingPlatform()).append("status", getStatus())
            .append("mark", getMark()).toString();
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

    public Date getTransactionDate() {
        return transactionDate;
    }

    public void setTransactionDate(Date transactionDate) {
        this.transactionDate = transactionDate;
    }

    public Date getInitiationDate() {
        return initiationDate;
    }

    public void setInitiationDate(Date initiationDate) {
        this.initiationDate = initiationDate;
    }

    public Date getRedemptionDate() {
        return redemptionDate;
    }

    public void setRedemptionDate(Date redemptionDate) {
        this.redemptionDate = redemptionDate;
    }

    public BigDecimal getTotalPrincipalAmount() {
        return totalPrincipalAmount;
    }

    public void setTotalPrincipalAmount(BigDecimal totalPrincipalAmount) {
        this.totalPrincipalAmount = totalPrincipalAmount;
    }

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(BigDecimal totalAmount) {
        this.totalAmount = totalAmount;
    }

    public BigDecimal getTotalPurchaseFee() {
        return totalPurchaseFee;
    }

    public void setTotalPurchaseFee(BigDecimal totalPurchaseFee) {
        this.totalPurchaseFee = totalPurchaseFee;
    }

    public BigDecimal getTotalRedemptionFee() {
        return totalRedemptionFee;
    }

    public void setTotalRedemptionFee(BigDecimal totalRedemptionFee) {
        this.totalRedemptionFee = totalRedemptionFee;
    }

    public BigDecimal getHeldShare() {
        return heldShare;
    }

    public void setHeldShare(BigDecimal heldShare) {
        this.heldShare = heldShare;
    }

    public Integer getHeldDays() {
        return heldDays;
    }

    public void setHeldDays(Integer heldDays) {
        this.heldDays = heldDays;
    }

    public Date getUpdateDate() {
        return updateDate;
    }

    public void setUpdateDate(Date updateDate) {
        this.updateDate = updateDate;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }

    public Integer getStatus() {
        return status;
    }

    public void setStatus(Integer status) {
        this.status = status;
    }

    public String getMark() {
        return mark;
    }

    public void setMark(String mark) {
        this.mark = mark;
    }
}

