package cn.sichu.entity;

import java.math.BigDecimal;
import java.util.Date;

/**
 * fund_position表
 *
 * @author sichu huang
 * @date 2024/03/16
 **/
public class FundPosition {
    private Long id;
    private String code;
    private Date transactionDate;
    private Date initiationDate;
    private BigDecimal totalAmount;
    private BigDecimal totalPurchaseFee;
    private BigDecimal heldShare;
    private Integer heldDays;
    private Date updateDate;

    public FundPosition() {
    }

    public FundPosition(Long id, String code, Date transactionDate, Date initiationDate, BigDecimal totalAmount,
        BigDecimal totalPurchaseFee, BigDecimal heldShare, Integer heldDays, Date updateDate) {
        this.id = id;
        this.code = code;
        this.transactionDate = transactionDate;
        this.initiationDate = initiationDate;
        this.totalAmount = totalAmount;
        this.totalPurchaseFee = totalPurchaseFee;
        this.heldShare = heldShare;
        this.heldDays = heldDays;
        this.updateDate = updateDate;
    }

    @Override
    public String toString() {
        return "FundPosition{" + "id=" + id + ", code='" + code + '\'' + ", transactionDate=" + transactionDate
            + ", initiationDate=" + initiationDate + ", totalAmount=" + totalAmount + ", totalPurchaseFee="
            + totalPurchaseFee + ", heldShare=" + heldShare + ", heldDays=" + heldDays + ", updateDate=" + updateDate
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
}

