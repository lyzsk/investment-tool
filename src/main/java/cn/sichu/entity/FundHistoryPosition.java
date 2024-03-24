package cn.sichu.entity;

import java.math.BigDecimal;
import java.util.Date;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
public class FundHistoryPosition {
    private Long id;
    private String code;
    private Date transactionDate;
    private Date initiationDate;
    private Date redemptionDate;
    private BigDecimal totalAmount;
    private BigDecimal totalPurchaseFee;
    private BigDecimal totalRedemptionFee;
    private BigDecimal heldShare;
    private Integer heldDays;
    private String mark;

    public FundHistoryPosition() {
    }

    public FundHistoryPosition(Long id, String code, Date transactionDate, Date initiationDate, Date redemptionDate, BigDecimal totalAmount,
        BigDecimal totalPurchaseFee, BigDecimal totalRedemptionFee, BigDecimal heldShare, Integer heldDays, String mark) {
        this.id = id;
        this.code = code;
        this.transactionDate = transactionDate;
        this.initiationDate = initiationDate;
        this.redemptionDate = redemptionDate;
        this.totalAmount = totalAmount;
        this.totalPurchaseFee = totalPurchaseFee;
        this.totalRedemptionFee = totalRedemptionFee;
        this.heldShare = heldShare;
        this.heldDays = heldDays;
        this.mark = mark;
    }

    @Override
    public String toString() {
        return "FundPositionHistory{" + "id=" + id + ", code='" + code + '\'' + ", transactionDate=" + transactionDate + ", initiationDate="
            + initiationDate + ", redemptionDate=" + redemptionDate + ", totalAmount=" + totalAmount + ", totalPurchaseFee=" + totalPurchaseFee
            + ", totalRedemptionFee=" + totalRedemptionFee + ", heldShare=" + heldShare + ", heldDays=" + heldDays + ", mark='" + mark + '\''
            + '}';
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

    public String getMark() {
        return mark;
    }

    public void setMark(String mark) {
        this.mark = mark;
    }
}
