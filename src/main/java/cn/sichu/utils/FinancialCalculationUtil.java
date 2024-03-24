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
        String rate = feeRate.replace("%", "");
        BigDecimal r = new BigDecimal(rate).divide(new BigDecimal("100"), 4, RoundingMode.CEILING);
        BigDecimal fee = v.multiply(r).setScale(2, RoundingMode.CEILING);
        return fee.toString();
    }

    /**
     * @param amount  买入金额
     * @param feeRate 申购费率
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/18
     **/
    public static BigDecimal calculatePurchaseFee(BigDecimal amount, String feeRate) {
        BigDecimal v = new BigDecimal(String.valueOf(amount));
        String rate = feeRate.replace("%", "");
        BigDecimal r = new BigDecimal(rate).divide(new BigDecimal("100"), 4, RoundingMode.CEILING);
        return v.multiply(r).setScale(2, RoundingMode.CEILING);
    }

    /**
     * @param share
     * @param nav
     * @param feeRate
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/12
     **/
    public static BigDecimal calculateRedemptionFee(BigDecimal share, String nav, String feeRate) {
        BigDecimal s = new BigDecimal(String.valueOf(share));
        BigDecimal n = new BigDecimal(nav);
        String rate = feeRate.replace("%", "");
        BigDecimal r = new BigDecimal(rate);
        BigDecimal amount = s.multiply(n).setScale(2, RoundingMode.CEILING);
        return amount.multiply(r).multiply(new BigDecimal("0.01")).setScale(2, RoundingMode.CEILING);
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

    /**
     * @param amount
     * @param fee
     * @param nav
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/18
     **/
    public static BigDecimal calculateShare(BigDecimal amount, BigDecimal fee, String nav) {
        BigDecimal v = new BigDecimal(String.valueOf(amount));
        BigDecimal f = new BigDecimal(String.valueOf(fee));
        BigDecimal n = new BigDecimal(nav);
        return v.subtract(f).divide(n, 2, RoundingMode.CEILING);
    }
}
