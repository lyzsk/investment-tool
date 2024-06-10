package cn.sichu.entity;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * gold_position
 *
 * @author sichu huang
 * @date 2024/06/10
 **/
public class GoldPosition {
    private Long id;
    private LocalDateTime purchaseTime;
    private LocalDateTime redemptionTime;
    private BigDecimal totalGrams;
    private BigDecimal totalPrincipalAmount;
    private BigDecimal totalAmount;
    private BigDecimal avgPricePerGram;
    private Integer heldDays;
    private String tradingPlatform;
    private String mark;

    public GoldPosition() {
    }

    public GoldPosition(Long id, LocalDateTime purchaseTime, LocalDateTime redemptionTime, BigDecimal totalGrams,
        BigDecimal totalPrincipalAmount, BigDecimal totalAmount, BigDecimal avgPricePerGram, Integer heldDays, String tradingPlatform,
        String mark) {
        this.id = id;
        this.purchaseTime = purchaseTime;
        this.redemptionTime = redemptionTime;
        this.totalGrams = totalGrams;
        this.totalPrincipalAmount = totalPrincipalAmount;
        this.totalAmount = totalAmount;
        this.avgPricePerGram = avgPricePerGram;
        this.heldDays = heldDays;
        this.tradingPlatform = tradingPlatform;
        this.mark = mark;
    }

    @Override
    public String toString() {
        return "GoldPosition{" + "id=" + id + ", purchaseTime=" + purchaseTime + ", redemptionTime=" + redemptionTime + ", totalGrams="
            + totalGrams + ", totalPrincipalAmount=" + totalPrincipalAmount + ", totalAmount=" + totalAmount + ", avgPricePerGram="
            + avgPricePerGram + ", heldDays=" + heldDays + ", tradingPlatform='" + tradingPlatform + '\'' + ", mark='" + mark + '\'' + '}';
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public LocalDateTime getPurchaseTime() {
        return purchaseTime;
    }

    public void setPurchaseTime(LocalDateTime purchaseTime) {
        this.purchaseTime = purchaseTime;
    }

    public LocalDateTime getRedemptionTime() {
        return redemptionTime;
    }

    public void setRedemptionTime(LocalDateTime redemptionTime) {
        this.redemptionTime = redemptionTime;
    }

    public BigDecimal getTotalGrams() {
        return totalGrams;
    }

    public void setTotalGrams(BigDecimal totalGrams) {
        this.totalGrams = totalGrams;
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

    public BigDecimal getAvgPricePerGram() {
        return avgPricePerGram;
    }

    public void setAvgPricePerGram(BigDecimal avgPricePerGram) {
        this.avgPricePerGram = avgPricePerGram;
    }

    public Integer getHeldDays() {
        return heldDays;
    }

    public void setHeldDays(Integer heldDays) {
        this.heldDays = heldDays;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }

    public String getMark() {
        return mark;
    }

    public void setMark(String mark) {
        this.mark = mark;
    }
}
