package cn.sichu.utils;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
public class FinancialCalculationUtil {

    /**
     * @param amount  买入金额
     * @param feeRate 申购费率
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/12
     **/
    public static String calculatePurchaseFee(String amount, String feeRate) {
        BigDecimal v = new BigDecimal(amount);
        BigDecimal r;

        if (feeRate.endsWith("%")) {
            String rate = feeRate.replace("%", "");
            r = new BigDecimal(rate).divide(new BigDecimal("100"), 4, RoundingMode.HALF_UP);
        } else {
            r = new BigDecimal(feeRate);
        }

        BigDecimal fee = v.multiply(r).setScale(2, RoundingMode.CEILING);
        return fee.toString();
    }

    /**
     * TODO: 赎回手续费逻辑: 先进先出, 从最早的一笔交易开始计算, 计算持有天数包含周末节假日, 每笔分别计算含金额的收益后, 费率向下取整, 2位小数
     *
     * @param share
     * @param nav
     * @param feeRate
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/12
     **/
    public static String calculateRedemptionFee(String share, String nav, String feeRate) {
        BigDecimal s = new BigDecimal(share);
        BigDecimal n = new BigDecimal(nav);
        String rate = feeRate.replace("%", "");
        BigDecimal r = new BigDecimal(rate);
        // 5138.29
        BigDecimal amount = s.multiply(n).setScale(2, RoundingMode.CEILING);
        // 15.64
        BigDecimal fee = amount.multiply(r).multiply(new BigDecimal("0.01")).setScale(2, RoundingMode.CEILING);
        return fee.toString();
    }

    /**
     * @param amount
     * @param fee
     * @param nav
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/13
     **/
    public static String calculateShare(String amount, String fee, String nav) {
        BigDecimal amountDecimal = new BigDecimal(amount);
        BigDecimal feeDecimal = new BigDecimal(fee);
        BigDecimal navDecimal = new BigDecimal(nav);
        BigDecimal shareDecimal = amountDecimal.subtract(feeDecimal).divide(navDecimal, 2, RoundingMode.CEILING);
        return shareDecimal.toString();
    }

    public static void main(String[] args) {
        System.out.println(calculatePurchaseFee("1000", "0.15%"));
        // 25.70
        System.err.println(calculateRedemptionFee("4193.84", "1.2252", "0.50%"));
    }
}
