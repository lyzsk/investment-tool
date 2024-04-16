package cn.sichu.domain;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

/**
 * "Fund Transaction Statement" 工作簿(Sheet)
 *
 * @author sichu huang
 * @date 2024/03/09
 **/
public class FundTransactionStatementSheet {
    /* 基金代码 */
    private String code;

    /* 基金简称 */
    private String shortName;

    /* 交易申请日 */
    private String applicationDate;

    /* 交易所属日 */
    private String transactionDate;

    /* 交易确认日 */
    private String confirmationDate;

    /* 交易到账日 */
    private String settlementDate;

    /* 手续费 */
    private String fee;

    /* 合计手续费 */
    private String totalFee;

    /* 份额 */
    private String share;

    /* 合计份额 */
    private String totalShare;

    /* 净值 */
    private String nav;

    /* 摊薄单价 */
    private String dilutedNav;

    /* 成本均价 */
    private String avgNavPerShare;

    /* (每股)现金分红 */
    private String dividendAmountPerShare;

    /* 交易金额 */
    private String amount;

    /* 合计金额 */
    private String totalAmount;

    /* 交易类型: purchase, redemption, dividend */
    private String type;

    /* 交易平台 */
    private String tradingPlatform;

    /* 基金全称 */
    private String fullName;

    /* 基金公司 */
    private String companyName;

    public FundTransactionStatementSheet() {
    }

    public FundTransactionStatementSheet(String code, String shortName, String applicationDate, String transactionDate, String confirmationDate,
        String settlementDate, String fee, String totalFee, String share, String totalShare, String nav, String dilutedNav,
        String avgNavPerShare, String dividendAmountPerShare, String amount, String totalAmount, String type, String tradingPlatform,
        String fullName, String companyName) {
        this.code = code;
        this.shortName = shortName;
        this.applicationDate = applicationDate;
        this.transactionDate = transactionDate;
        this.confirmationDate = confirmationDate;
        this.settlementDate = settlementDate;
        this.fee = fee;
        this.totalFee = totalFee;
        this.share = share;
        this.totalShare = totalShare;
        this.nav = nav;
        this.dilutedNav = dilutedNav;
        this.avgNavPerShare = avgNavPerShare;
        this.dividendAmountPerShare = dividendAmountPerShare;
        this.amount = amount;
        this.totalAmount = totalAmount;
        this.type = type;
        this.tradingPlatform = tradingPlatform;
        this.fullName = fullName;
        this.companyName = companyName;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("code", getCode()).append("shortName", getShortName())
            .append("applicationDate", getApplicationDate()).append("transactionDate", getTransactionDate())
            .append("confirmationDate", getConfirmationDate()).append("settlementDate", getSettlementDate()).append("fee", getFee())
            .append("totalFee", getTotalFee()).append("share", getShare()).append("totalShare", getTotalShare()).append("nav", getNav())
            .append("dilutedNav", getDilutedNav()).append("avgNavPerShare", getAvgNavPerShare())
            .append("dividendAmountPerShare", getDividendAmountPerShare()).append("amount", getAmount()).append("totalAmount", getTotalAmount())
            .append("type", getType()).append("tradingPlatform", getTradingPlatform()).append("fullName", getFullName())
            .append("companyName", getCompanyName()).toString();
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getShortName() {
        return shortName;
    }

    public void setShortName(String shortName) {
        this.shortName = shortName;
    }

    public String getApplicationDate() {
        return applicationDate;
    }

    public void setApplicationDate(String applicationDate) {
        this.applicationDate = applicationDate;
    }

    public String getTransactionDate() {
        return transactionDate;
    }

    public void setTransactionDate(String transactionDate) {
        this.transactionDate = transactionDate;
    }

    public String getConfirmationDate() {
        return confirmationDate;
    }

    public void setConfirmationDate(String confirmationDate) {
        this.confirmationDate = confirmationDate;
    }

    public String getSettlementDate() {
        return settlementDate;
    }

    public void setSettlementDate(String settlementDate) {
        this.settlementDate = settlementDate;
    }

    public String getFee() {
        return fee;
    }

    public void setFee(String fee) {
        this.fee = fee;
    }

    public String getTotalFee() {
        return totalFee;
    }

    public void setTotalFee(String totalFee) {
        this.totalFee = totalFee;
    }

    public String getShare() {
        return share;
    }

    public void setShare(String share) {
        this.share = share;
    }

    public String getTotalShare() {
        return totalShare;
    }

    public void setTotalShare(String totalShare) {
        this.totalShare = totalShare;
    }

    public String getNav() {
        return nav;
    }

    public void setNav(String nav) {
        this.nav = nav;
    }

    public String getDilutedNav() {
        return dilutedNav;
    }

    public void setDilutedNav(String dilutedNav) {
        this.dilutedNav = dilutedNav;
    }

    public String getAvgNavPerShare() {
        return avgNavPerShare;
    }

    public void setAvgNavPerShare(String avgNavPerShare) {
        this.avgNavPerShare = avgNavPerShare;
    }

    public String getDividendAmountPerShare() {
        return dividendAmountPerShare;
    }

    public void setDividendAmountPerShare(String dividendAmountPerShare) {
        this.dividendAmountPerShare = dividendAmountPerShare;
    }

    public String getAmount() {
        return amount;
    }

    public void setAmount(String amount) {
        this.amount = amount;
    }

    public String getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(String totalAmount) {
        this.totalAmount = totalAmount;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }

    public String getFullName() {
        return fullName;
    }

    public void setFullName(String fullName) {
        this.fullName = fullName;
    }

    public String getCompanyName() {
        return companyName;
    }

    public void setCompanyName(String companyName) {
        this.companyName = companyName;
    }
}
