package cn.sichu.service;

import java.io.IOException;

/**
 * @author sichu huang
 * @date 2024/06/10
 **/
public interface IGoldTransactionService {
    /**
     * @param pricePerGram    pricePerGram
     * @param grams           grams
     * @param transactionTime transactionTime
     * @param tradingPlatform tradingPlatform
     * @author sichu huang
     * @date 2024/06/10
     **/
    void purchaseGold(String pricePerGram, String grams, String transactionTime, String tradingPlatform) throws IOException;

    /**
     * @param pricePerGram    pricePerGram
     * @param grams           grams
     * @param transactionTime transactionTime
     * @param tradingPlatform tradingPlatform
     * @author sichu huang
     * @date 2024/06/10
     **/
    void redeemGold(String pricePerGram, String grams, String transactionTime, String tradingPlatform) throws IOException;

    void updateHeldDays() throws IOException;
}
