package cn.sichu.entity;

import java.util.Date;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
public class FundPurchaseTransaction {
    private Long id;
    private String code;
    private Date applicationDate;
    private Date transactionDate;
    private Date confirmationDate;
    private Date settlementDate;
    private String fee;
    private String share;
    private String nav;
    private String amount;
    private String tradingPlatform;
    private Integer status;
    private String mark;

    public FundPurchaseTransaction() {
    }

    public FundPurchaseTransaction(Long id, String code, Date applicationDate, Date transactionDate,
        Date confirmationDate, Date settlementDate, String fee, String share, String nav, String amount,
        String tradingPlatform, Integer status, String mark) {
        this.id = id;
        this.code = code;
        this.applicationDate = applicationDate;
        this.transactionDate = transactionDate;
        this.confirmationDate = confirmationDate;
        this.settlementDate = settlementDate;
        this.fee = fee;
        this.share = share;
        this.nav = nav;
        this.amount = amount;
        this.tradingPlatform = tradingPlatform;
        this.status = status;
        this.mark = mark;
    }

    @Override
    public String toString() {
        return "FundPurchaseTransaction{" + "id=" + id + ", code='" + code + '\'' + ", applicationDate="
            + applicationDate + ", transactionDate=" + transactionDate + ", confirmationDate=" + confirmationDate
            + ", settlementDate=" + settlementDate + ", fee='" + fee + '\'' + ", share='" + share + '\'' + ", nav='"
            + nav + '\'' + ", amount='" + amount + '\'' + ", tradingPlatform='" + tradingPlatform + '\'' + ", status="
            + status + ", mark='" + mark + '\'' + '}';
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

    public Date getApplicationDate() {
        return applicationDate;
    }

    public void setApplicationDate(Date applicationDate) {
        this.applicationDate = applicationDate;
    }

    public Date getTransactionDate() {
        return transactionDate;
    }

    public void setTransactionDate(Date transactionDate) {
        this.transactionDate = transactionDate;
    }

    public Date getConfirmationDate() {
        return confirmationDate;
    }

    public void setConfirmationDate(Date confirmationDate) {
        this.confirmationDate = confirmationDate;
    }

    public Date getSettlementDate() {
        return settlementDate;
    }

    public void setSettlementDate(Date settlementDate) {
        this.settlementDate = settlementDate;
    }

    public String getFee() {
        return fee;
    }

    public void setFee(String fee) {
        this.fee = fee;
    }

    public String getShare() {
        return share;
    }

    public void setShare(String share) {
        this.share = share;
    }

    public String getNav() {
        return nav;
    }

    public void setNav(String nav) {
        this.nav = nav;
    }

    public String getAmount() {
        return amount;
    }

    public void setAmount(String amount) {
        this.amount = amount;
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
