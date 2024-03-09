package cn.sichu.domain;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

/**
 * "Gold Transaction Statement" 工作簿(Sheet)
 *
 * @author sichu huang
 * @date 2024/03/09
 **/
public class GoldTransactionStatementSheet {
    /* 名称 */
    private String name;

    /* 交易申请日 */
    private String applicationDate;

    /* 交易确认日 */
    private String confirmationDate;

    /* 交易到账日 */
    private String settlementDate;

    /* 交易金额/克 */
    private String amountPerGram;

    /* 交易金额 */
    private String amount;

    /* 克数 */
    private String grams;

    /* 合计克数 */
    private String totalGrams;

    /* 合计金额 */
    private String totalAmount;

    /* 平均交易金额/克 */
    private String avgAmountPerGram;

    /* 交易类型 */
    private String type;

    /* 交易平台 */
    private String tradingPlatform;

    public GoldTransactionStatementSheet() {
    }

    public GoldTransactionStatementSheet(String name, String applicationDate, String confirmationDate,
        String settlementDate, String amountPerGram, String amount, String grams, String totalGrams, String totalAmount,
        String avgAmountPerGram, String type, String tradingPlatform) {
        this.name = name;
        this.applicationDate = applicationDate;
        this.confirmationDate = confirmationDate;
        this.settlementDate = settlementDate;
        this.amountPerGram = amountPerGram;
        this.amount = amount;
        this.grams = grams;
        this.totalGrams = totalGrams;
        this.totalAmount = totalAmount;
        this.avgAmountPerGram = avgAmountPerGram;
        this.type = type;
        this.tradingPlatform = tradingPlatform;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("name", getName())
            .append("applicationDate", getApplicationDate()).append("confirmationDate", getConfirmationDate())
            .append("settlementDate", getSettlementDate()).append("amountPerGram", getAmountPerGram())
            .append("amount", getAmount()).append("grams", getGrams()).append("totalGrams", getTotalGrams())
            .append("totalAmount", getTotalAmount()).append("avgAmountPerGram", getAvgAmountPerGram())
            .append("type", getType()).append("tradingPlatform", getTradingPlatform()).toString();
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getApplicationDate() {
        return applicationDate;
    }

    public void setApplicationDate(String applicationDate) {
        this.applicationDate = applicationDate;
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

    public String getAmountPerGram() {
        return amountPerGram;
    }

    public void setAmountPerGram(String amountPerGram) {
        this.amountPerGram = amountPerGram;
    }

    public String getAmount() {
        return amount;
    }

    public void setAmount(String amount) {
        this.amount = amount;
    }

    public String getGrams() {
        return grams;
    }

    public void setGrams(String grams) {
        this.grams = grams;
    }

    public String getTotalGrams() {
        return totalGrams;
    }

    public void setTotalGrams(String totalGrams) {
        this.totalGrams = totalGrams;
    }

    public String getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(String totalAmount) {
        this.totalAmount = totalAmount;
    }

    public String getAvgAmountPerGram() {
        return avgAmountPerGram;
    }

    public void setAvgAmountPerGram(String avgAmountPerGram) {
        this.avgAmountPerGram = avgAmountPerGram;
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

}
