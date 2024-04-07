package cn.sichu.entity;

import java.math.BigDecimal;
import java.util.Date;

/**
 * `fund_dividend_transaction` 实体类
 *
 * @author sichu huang
 * @date 2024/04/07
 **/
public class FundDividendTransaction {
    private Long id;
    private String code;
    private Date applicationDate;
    private Date transactionDate;
    private Date confirmationDate;
    private Date settlementDate;
    private BigDecimal amount;
    private BigDecimal share;
    private BigDecimal dividendAmountPerShare;
    private String tradingPlatform;
    private Integer status;
    private String mark;

    public FundDividendTransaction() {
    }

    public FundDividendTransaction(Long id, String code, Date applicationDate, Date transactionDate, Date confirmationDate, Date settlementDate,
        BigDecimal amount, BigDecimal share, BigDecimal dividendAmountPerShare, String tradingPlatform, Integer status, String mark) {
        this.id = id;
        this.code = code;
        this.applicationDate = applicationDate;
        this.transactionDate = transactionDate;
        this.confirmationDate = confirmationDate;
        this.settlementDate = settlementDate;
        this.amount = amount;
        this.share = share;
        this.dividendAmountPerShare = dividendAmountPerShare;
        this.tradingPlatform = tradingPlatform;
        this.status = status;
        this.mark = mark;
    }

    @Override
    public String toString() {
        return "FundDividendTransaction{" + "id=" + id + ", code='" + code + '\'' + ", applicationDate=" + applicationDate + ", transactionDate="
            + transactionDate + ", confirmationDate=" + confirmationDate + ", settlementDate=" + settlementDate + ", amount=" + amount
            + ", share=" + share + ", dividendAmountPerShare=" + dividendAmountPerShare + ", tradingPlatform='" + tradingPlatform + '\''
            + ", status=" + status + ", mark='" + mark + '\'' + '}';
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

    public BigDecimal getShare() {
        return share;
    }

    public void setShare(BigDecimal share) {
        this.share = share;
    }

    public BigDecimal getDividendAmountPerShare() {
        return dividendAmountPerShare;
    }

    public void setDividendAmountPerShare(BigDecimal dividendAmountPerShare) {
        this.dividendAmountPerShare = dividendAmountPerShare;
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
