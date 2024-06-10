package cn.sichu.domain;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

/**
 * "Gold Transaction Summary" 工作簿(Sheet)
 *
 * @author sichu huang
 * @date 2024/03/09
 **/
public class GoldTransactionSummarySheet {

    /* 交易类型 */
    private String type;

    /* 购买时间 */
    private String purchaseTime;

    /* 赎回时间 */
    private String redemptionTime;

    /* 交易金额 */
    private String amount;

    /* 交易金额/克 */
    private String pricePerGram;

    /* 克数 */
    private String grams;

    /* 交易平台 */
    private String tradingPlatform;

    /* 累计收益 */
    private String sumProfit;

    /* 累计收益率 */
    private String sumYieldRate;

    /* 累计本金 */
    private String sumPrincipalAmount;

    /* 累计金额 */
    private String sumAmount;

    /* 平均交易金额/克 */
    private String avgAmountPerGram;

    /* 合计克数 */
    private String sumGrams;

    public GoldTransactionSummarySheet() {
    }

    public GoldTransactionSummarySheet(String type, String purchaseTime, String redemptionTime, String amount, String pricePerGram, String grams,
        String tradingPlatform, String sumProfit, String sumYieldRate, String sumPrincipalAmount, String sumAmount, String avgAmountPerGram,
        String sumGrams) {
        this.type = type;
        this.purchaseTime = purchaseTime;
        this.redemptionTime = redemptionTime;
        this.amount = amount;
        this.pricePerGram = pricePerGram;
        this.grams = grams;
        this.tradingPlatform = tradingPlatform;
        this.sumProfit = sumProfit;
        this.sumYieldRate = sumYieldRate;
        this.sumPrincipalAmount = sumPrincipalAmount;
        this.sumAmount = sumAmount;
        this.avgAmountPerGram = avgAmountPerGram;
        this.sumGrams = sumGrams;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("type", getType()).append("purchaseTime", getPurchaseTime())
            .append("redemptionTime", getRedemptionTime()).append("amount", getAmount()).append("pricePerGram", getPricePerGram())
            .append("grams", getGrams()).append("tradingPlatform", getTradingPlatform()).append("sumProfit", getSumProfit())
            .append("sumYieldRate", getSumYieldRate()).append("sumPrinciaplAmount", getSumPrincipalAmount()).append("sumAmount", getSumAmount())
            .append("avgAmountPerGram", getAvgAmountPerGram()).append("sumGrams", getSumGrams()).toString();
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getPurchaseTime() {
        return purchaseTime;
    }

    public void setPurchaseTime(String purchaseTime) {
        this.purchaseTime = purchaseTime;
    }

    public String getRedemptionTime() {
        return redemptionTime;
    }

    public void setRedemptionTime(String redemptionTime) {
        this.redemptionTime = redemptionTime;
    }

    public String getAmount() {
        return amount;
    }

    public void setAmount(String amount) {
        this.amount = amount;
    }

    public String getPricePerGram() {
        return pricePerGram;
    }

    public void setPricePerGram(String pricePerGram) {
        this.pricePerGram = pricePerGram;
    }

    public String getGrams() {
        return grams;
    }

    public void setGrams(String grams) {
        this.grams = grams;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }

    public String getSumProfit() {
        return sumProfit;
    }

    public void setSumProfit(String sumProfit) {
        this.sumProfit = sumProfit;
    }

    public String getSumYieldRate() {
        return sumYieldRate;
    }

    public void setSumYieldRate(String sumYieldRate) {
        this.sumYieldRate = sumYieldRate;
    }

    public String getSumPrincipalAmount() {
        return sumPrincipalAmount;
    }

    public void setSumPrincipalAmount(String sumPrincipalAmount) {
        this.sumPrincipalAmount = sumPrincipalAmount;
    }

    public String getSumAmount() {
        return sumAmount;
    }

    public void setSumAmount(String sumAmount) {
        this.sumAmount = sumAmount;
    }

    public String getAvgAmountPerGram() {
        return avgAmountPerGram;
    }

    public void setAvgAmountPerGram(String avgAmountPerGram) {
        this.avgAmountPerGram = avgAmountPerGram;
    }

    public String getSumGrams() {
        return sumGrams;
    }

    public void setSumGrams(String sumGrams) {
        this.sumGrams = sumGrams;
    }
}
