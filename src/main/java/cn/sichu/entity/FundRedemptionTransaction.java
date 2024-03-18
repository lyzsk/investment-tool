package cn.sichu.entity;

import java.math.BigDecimal;
import java.util.Date;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
public class FundRedemptionTransaction {
    private Long id;
    private String code;
    private Date applicationDate;
    private Date transactionDate;
    private Date confirmationDate;
    private Date settlementDate;
    private BigDecimal amount;
    private BigDecimal fee;
    private BigDecimal nav;
    private BigDecimal share;
    private String tradingPlatform;
    private Integer status;
    private String mark;

    public FundRedemptionTransaction() {
    }

    public FundRedemptionTransaction(Long id, String code, Date applicationDate, Date transactionDate,
        Date confirmationDate, Date settlementDate, BigDecimal amount, BigDecimal fee, BigDecimal nav, BigDecimal share,
        String tradingPlatform, Integer status, String mark) {
        this.id = id;
        this.code = code;
        this.applicationDate = applicationDate;
        this.transactionDate = transactionDate;
        this.confirmationDate = confirmationDate;
        this.settlementDate = settlementDate;
        this.amount = amount;
        this.fee = fee;
        this.nav = nav;
        this.share = share;
        this.tradingPlatform = tradingPlatform;
        this.status = status;
        this.mark = mark;
    }

    @Override
    public String toString() {
        return "FundRedemptionTransaction{" + "id=" + id + ", code='" + code + '\'' + ", applicationDate="
            + applicationDate + ", transactionDate=" + transactionDate + ", confirmationDate=" + confirmationDate
            + ", settlementDate=" + settlementDate + ", amount=" + amount + ", fee=" + fee + ", nav=" + nav + ", share="
            + share + ", tradingPlatform='" + tradingPlatform + '\'' + ", status=" + status + ", mark='" + mark + '\''
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

    public BigDecimal getAmount() {
        return amount;
    }

    public void setAmount(BigDecimal amount) {
        this.amount = amount;
    }

    public BigDecimal getFee() {
        return fee;
    }

    public void setFee(BigDecimal fee) {
        this.fee = fee;
    }

    public BigDecimal getNav() {
        return nav;
    }

    public void setNav(BigDecimal nav) {
        this.nav = nav;
    }

    public BigDecimal getShare() {
        return share;
    }

    public void setShare(BigDecimal share) {
        this.share = share;
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
