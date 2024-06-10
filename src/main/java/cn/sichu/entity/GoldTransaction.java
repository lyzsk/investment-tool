package cn.sichu.entity;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * gold_transaction
 *
 * @author sichu huang
 * @date 2024/06/10
 **/
public class GoldTransaction {
    private Long id;
    private BigDecimal pricePerGram;
    private BigDecimal grams;
    private Integer type;
    private LocalDateTime transactionTime;
    private String tradingPlatform;
    private String mark;

    public GoldTransaction() {
    }

    public GoldTransaction(BigDecimal pricePerGram, BigDecimal grams, LocalDateTime transactionTime, String tradingPlatform) {
        this.pricePerGram = pricePerGram;
        this.grams = grams;
        this.transactionTime = transactionTime;
        this.tradingPlatform = tradingPlatform;
    }

    public GoldTransaction(Long id, BigDecimal pricePerGram, BigDecimal grams, Integer type, LocalDateTime transactionTime,
        String tradingPlatform, String mark) {
        this.id = id;
        this.pricePerGram = pricePerGram;
        this.grams = grams;
        this.type = type;
        this.transactionTime = transactionTime;
        this.tradingPlatform = tradingPlatform;
        this.mark = mark;
    }

    @Override
    public String toString() {
        return "GoldTransaction{" + "id=" + id + ", pricePerGram=" + pricePerGram + ", grams=" + grams + ", type=" + type + ", transactionTime="
            + transactionTime + ", tradingPlatform='" + tradingPlatform + '\'' + ", mark='" + mark + '\'' + '}';
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public BigDecimal getPricePerGram() {
        return pricePerGram;
    }

    public void setPricePerGram(BigDecimal pricePerGram) {
        this.pricePerGram = pricePerGram;
    }

    public BigDecimal getGrams() {
        return grams;
    }

    public void setGrams(BigDecimal grams) {
        this.grams = grams;
    }

    public Integer getType() {
        return type;
    }

    public void setType(Integer type) {
        this.type = type;
    }

    public LocalDateTime getTransactionTime() {
        return transactionTime;
    }

    public void setTransactionTime(LocalDateTime transactionTime) {
        this.transactionTime = transactionTime;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }

    public String getMark() {
        return mark;
    }

    public void setMark(String mark) {
        this.mark = mark;
    }
}
