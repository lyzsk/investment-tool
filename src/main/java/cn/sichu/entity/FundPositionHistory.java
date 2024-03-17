package cn.sichu.entity;

import java.util.Date;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
public class FundPositionHistory {
    private Long id;
    private String code;
    private Date transactionDate;
    private Date initiationDate;
    private Date redemptionDate;
    private String totalAmount;
    private String totalPurchaseFee;
    private String totalRedemptionFee;
    private String heldShare;
    private Integer heldDays;
    private String mark;

    public FundPositionHistory() {
    }

    public FundPositionHistory(Long id, String code, Date transactionDate, Date initiationDate, Date redemptionDate,
        String totalAmount, String totalPurchaseFee, String totalRedemptionFee, String heldShare, Integer heldDays,
        String mark) {
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
        return "FundPositionHistory{" + "id=" + id + ", code='" + code + '\'' + ", transactionDate=" + transactionDate
            + ", initiationDate=" + initiationDate + ", redemptionDate=" + redemptionDate + ", totalAmount='"
            + totalAmount + '\'' + ", totalPurchaseFee='" + totalPurchaseFee + '\'' + ", totalRedemptionFee='"
            + totalRedemptionFee + '\'' + ", heldShare='" + heldShare + '\'' + ", heldDays=" + heldDays + ", mark='"
            + mark + '\'' + '}';
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

    public String getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(String totalAmount) {
        this.totalAmount = totalAmount;
    }

    public String getTotalPurchaseFee() {
        return totalPurchaseFee;
    }

    public void setTotalPurchaseFee(String totalPurchaseFee) {
        this.totalPurchaseFee = totalPurchaseFee;
    }

    public String getTotalRedemptionFee() {
        return totalRedemptionFee;
    }

    public void setTotalRedemptionFee(String totalRedemptionFee) {
        this.totalRedemptionFee = totalRedemptionFee;
    }

    public String getHeldShare() {
        return heldShare;
    }

    public void setHeldShare(String heldShare) {
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
