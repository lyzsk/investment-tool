package cn.sichu.utils;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
public class FinancialCalculationUtil {

    /**
     * @param amount  amount
     * @param feeRate feeRate
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/18
     **/
    public static BigDecimal calculatePurchaseFee(BigDecimal amount, String feeRate) {
        String rate = feeRate.replace("%", "");
        BigDecimal r = new BigDecimal(rate).divide(new BigDecimal("100"), 4, RoundingMode.CEILING);
        return amount.multiply(r).setScale(2, RoundingMode.CEILING);
    }

    /**
     * @param share   share
     * @param nav     nav
     * @param feeRate feeRate
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/12
     **/
    public static BigDecimal calculateRedemptionFee(BigDecimal share, String nav, String feeRate) {
        BigDecimal n = new BigDecimal(nav);
        String rate = feeRate.replace("%", "");
        BigDecimal r = new BigDecimal(rate).divide(new BigDecimal("100"), 4, RoundingMode.CEILING);
        BigDecimal amount = share.multiply(n).setScale(2, RoundingMode.CEILING);
        return amount.multiply(r).setScale(2, RoundingMode.CEILING);
    }

    /**
     * @param share share
     * @param nav   nav
     * @param fee   fee
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/25
     **/
    public static BigDecimal calculateRedemptionAmount(BigDecimal share, String nav, BigDecimal fee) {
        BigDecimal n = new BigDecimal(nav);
        return share.multiply(n).subtract(fee).setScale(2, RoundingMode.CEILING);
    }

    /**
     * @param amount amount
     * @param fee    fee
     * @param nav    nav
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/18
     **/
    public static BigDecimal calculateShare(BigDecimal amount, BigDecimal fee, String nav) {
        BigDecimal n = new BigDecimal(nav);
        return amount.subtract(fee).divide(n, 2, RoundingMode.HALF_DOWN);
    }
}
