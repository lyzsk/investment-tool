package cn.sichu.domain;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

/**
 * "Fund Transaction Report" 工作簿(Sheet)
 *
 * @author sichu huang
 * @date 2024/03/09
 **/
public class FundTransactionReportSheet {
    /* 编号 */
    private String code;

    /* 基金简称 */
    private String shortName;

    /* 购买交易所属日 */
    private String purchaseTransactionDate;

    /* 赎回交易所属日 */
    private String redemptionTransactionDate;

    /* 分红交易所属日 */
    private String dividendDate;

    /* 持有天数 */
    private String heldDays;

    /* 合计本金 */
    private String totalPrincipalAmount;

    /* 合计金额 */
    private String totalAmount;

    /* 净收益 */
    private String profit;

    /* 日均万份收益 */
    private String dailyNavYield;

    /* 交易平台 */
    private String tradingPlatform;

    /* 基金公司 */
    private String companyName;

    public FundTransactionReportSheet() {
    }

    public FundTransactionReportSheet(String code, String shortName, String purchaseTransactionDate, String redemptionTransactionDate,
        String dividendDate, String heldDays, String totalPrincipalAmount, String totalAmount, String profit, String dailyNavYield,
        String tradingPlatform, String companyName) {
        this.code = code;
        this.shortName = shortName;
        this.purchaseTransactionDate = purchaseTransactionDate;
        this.redemptionTransactionDate = redemptionTransactionDate;
        this.dividendDate = dividendDate;
        this.heldDays = heldDays;
        this.totalPrincipalAmount = totalPrincipalAmount;
        this.totalAmount = totalAmount;
        this.profit = profit;
        this.dailyNavYield = dailyNavYield;
        this.tradingPlatform = tradingPlatform;
        this.companyName = companyName;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("code", getCode()).append("shortName", getShortName())
            .append("purchaseTransactionDate", getPurchaseTransactionDate()).append("redemptionTransactionDate", getRedemptionTransactionDate())
            .append("dividendDate", getDividendDate()).append("heldDays", getHeldDays())
            .append("totalPrincipalAmount", getTotalPrincipalAmount()).append("totalAmount", getTotalAmount()).append("profit", getProfit())
            .append("dailyNavYield", getDailyNavYield()).append("tradingPlatform", getTradingPlatform()).append("companyName", getCompanyName())
            .toString();
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

    public String getPurchaseTransactionDate() {
        return purchaseTransactionDate;
    }

    public void setPurchaseTransactionDate(String purchaseTransactionDate) {
        this.purchaseTransactionDate = purchaseTransactionDate;
    }

    public String getRedemptionTransactionDate() {
        return redemptionTransactionDate;
    }

    public void setRedemptionTransactionDate(String redemptionTransactionDate) {
        this.redemptionTransactionDate = redemptionTransactionDate;
    }

    public String getDividendDate() {
        return dividendDate;
    }

    public void setDividendDate(String dividendDate) {
        this.dividendDate = dividendDate;
    }

    public String getHeldDays() {
        return heldDays;
    }

    public void setHeldDays(String heldDays) {
        this.heldDays = heldDays;
    }

    public String getTotalPrincipalAmount() {
        return totalPrincipalAmount;
    }

    public void setTotalPrincipalAmount(String totalPrincipalAmount) {
        this.totalPrincipalAmount = totalPrincipalAmount;
    }

    public String getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(String totalAmount) {
        this.totalAmount = totalAmount;
    }

    public String getProfit() {
        return profit;
    }

    public void setProfit(String profit) {
        this.profit = profit;
    }

    public String getDailyNavYield() {
        return dailyNavYield;
    }

    public void setDailyNavYield(String dailyNavYield) {
        this.dailyNavYield = dailyNavYield;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }

    public String getCompanyName() {
        return companyName;
    }

    public void setCompanyName(String companyName) {
        this.companyName = companyName;
    }
}
