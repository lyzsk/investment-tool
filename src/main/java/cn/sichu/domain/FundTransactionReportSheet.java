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

    /* 购买交易申请日 */
    private String purchaseApplicationDate;

    /* 赎回交易申请日 */
    private String redemptionApplicationDate;

    /* 分红交易日 */
    private String dividendDate;

    /* 持有天数 */
    private String heldDate;

    /* 净收益 */
    private String profit;

    /* 日均万份收益 */
    private String dailyNavYield;

    /* 基金公司 */
    private String companyName;

    /* 交易平台 */
    private String tradingPlatform;

    public FundTransactionReportSheet() {
    }

    public FundTransactionReportSheet(String code, String shortName, String purchaseApplicationDate,
        String redemptionApplicationDate, String dividendDate, String heldDate, String profit, String dailyNavYield,
        String companyName, String tradingPlatform) {
        this.code = code;
        this.shortName = shortName;
        this.purchaseApplicationDate = purchaseApplicationDate;
        this.redemptionApplicationDate = redemptionApplicationDate;
        this.dividendDate = dividendDate;
        this.heldDate = heldDate;
        this.profit = profit;
        this.dailyNavYield = dailyNavYield;
        this.companyName = companyName;
        this.tradingPlatform = tradingPlatform;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("code", getCode())
            .append("shortName", getShortName()).append("purchaseApplicationDate", getPurchaseApplicationDate())
            .append("redemptionApplicationDate", getRedemptionApplicationDate())
            .append("dividendDate", getDividendDate()).append("heldDate", getHeldDate()).append("profit", getProfit())
            .append("dailyNavYield", getDailyNavYield()).append("companyName", getCompanyName())
            .append("tradingPlatform", getTradingPlatform()).toString();
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

    public String getPurchaseApplicationDate() {
        return purchaseApplicationDate;
    }

    public void setPurchaseApplicationDate(String purchaseApplicationDate) {
        this.purchaseApplicationDate = purchaseApplicationDate;
    }

    public String getRedemptionApplicationDate() {
        return redemptionApplicationDate;
    }

    public void setRedemptionApplicationDate(String redemptionApplicationDate) {
        this.redemptionApplicationDate = redemptionApplicationDate;
    }

    public String getDividendDate() {
        return dividendDate;
    }

    public void setDividendDate(String dividendDate) {
        this.dividendDate = dividendDate;
    }

    public String getHeldDate() {
        return heldDate;
    }

    public void setHeldDate(String heldDate) {
        this.heldDate = heldDate;
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

    public String getCompanyName() {
        return companyName;
    }

    public void setCompanyName(String companyName) {
        this.companyName = companyName;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }
}
