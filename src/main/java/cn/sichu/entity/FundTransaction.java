package cn.sichu.entity;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

import java.math.BigDecimal;
import java.util.Date;

/**
 * `fund_transaction` 实体类
 *
 * @author sichu huang
 * @date 2024/03/09
 **/
public class FundTransaction {
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
    private BigDecimal dividendAmountPerShare;
    private String tradingPlatform;
    private Integer status;
    private String mark;
    private Integer type;

    public FundTransaction() {
    }

    public FundTransaction(Long id, String code, Date applicationDate, Date transactionDate, Date confirmationDate, Date settlementDate,
        BigDecimal amount, BigDecimal fee, BigDecimal nav, BigDecimal share, BigDecimal dividendAmountPerShare, String tradingPlatform,
        Integer status, String mark, Integer type) {
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
        this.dividendAmountPerShare = dividendAmountPerShare;
        this.tradingPlatform = tradingPlatform;
        this.status = status;
        this.mark = mark;
        this.type = type;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("id", getId()).append("code", getCode())
            .append("applicationDate", getApplicationDate()).append("transactionDate", getTransactionDate())
            .append("confirmationDate", getConfirmationDate()).append("settlementDate", getSettlementDate()).append("amount", getAmount())
            .append("fee", getFee()).append("nav", getNav()).append("share", getShare())
            .append("dividendAmountPerShare", getDividendAmountPerShare()).append("transactionPlatform", getTradingPlatform())
            .append("status", getStatus()).append("mark", getMark()).append("type", getType()).toString();
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

    public Integer getType() {
        return type;
    }

    public void setType(Integer type) {
        this.type = type;
    }
}
