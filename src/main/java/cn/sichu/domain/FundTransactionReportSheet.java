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

    /* 持有天数 */
    private String heldDays;

    /* 合计本金 */
    private String totalPrincipalAmount;

    /* 合计金额 */
    private String totalAmount;

    /* 分红次数 */
    private String dividendCount;

    /* 合计分红金额 */
    private String totalDividendAmount;

    /* 净收益 */
    private String profit;

    /* 日均万份收益 */
    private String dailyNavYield;

    /* 收益率 */
    private String yieldRate;

    /* 交易平台 */
    private String tradingPlatform;

    /* 基金公司 */
    private String companyName;

    public FundTransactionReportSheet() {
    }

    public FundTransactionReportSheet(String code, String shortName, String purchaseTransactionDate, String redemptionTransactionDate,
        String heldDays, String totalPrincipalAmount, String totalAmount, String dividendCount, String totalDividendAmount, String profit,
        String dailyNavYield, String yieldRate, String tradingPlatform, String companyName) {
        this.code = code;
        this.shortName = shortName;
        this.purchaseTransactionDate = purchaseTransactionDate;
        this.redemptionTransactionDate = redemptionTransactionDate;
        this.heldDays = heldDays;
        this.totalPrincipalAmount = totalPrincipalAmount;
        this.totalAmount = totalAmount;
        this.dividendCount = dividendCount;
        this.totalDividendAmount = totalDividendAmount;
        this.profit = profit;
        this.dailyNavYield = dailyNavYield;
        this.yieldRate = yieldRate;
        this.tradingPlatform = tradingPlatform;
        this.companyName = companyName;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("code", getCode()).append("shortName", getShortName())
            .append("purchaseTransactionDate", getPurchaseTransactionDate()).append("redemptionTransactionDate", getRedemptionTransactionDate())
            .append("heldDays", getHeldDays()).append("totalPrincipalAmount", getTotalPrincipalAmount()).append("totalAmount", getTotalAmount())
            .append("dividendCount", getDividendCount()).append("totalDividendAmount", getTotalDividendAmount()).append("profit", getProfit())
            .append("dailyNavYield", getDailyNavYield()).append("yieldRate", getYieldRate()).append("tradingPlatform", getTradingPlatform())
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

    public String getDividendCount() {
        return dividendCount;
    }

    public void setDividendCount(String dividendCount) {
        this.dividendCount = dividendCount;
    }

    public String getTotalDividendAmount() {
        return totalDividendAmount;
    }

    public void setTotalDividendAmount(String totalDividendAmount) {
        this.totalDividendAmount = totalDividendAmount;
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

    public String getYieldRate() {
        return yieldRate;
    }

    public void setYieldRate(String yieldRate) {
        this.yieldRate = yieldRate;
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
