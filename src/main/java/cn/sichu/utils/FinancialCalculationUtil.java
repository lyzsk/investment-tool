package cn.sichu.utils;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
public class FinancialCalculationUtil {

    /**
     * @param amount
     * @param feeRate
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/12
     **/
    public static String calculatePurchaseFee(String amount, String feeRate) {
        BigDecimal v = new BigDecimal(amount);
        String rate = feeRate.replace("%", "");
        BigDecimal r = new BigDecimal(rate);
        BigDecimal fee = v.multiply(r).multiply(new BigDecimal("0.01")).setScale(2, RoundingMode.CEILING);
        return fee.toString();
    }

    /**
     * TODO: 赎回手续费计算逻辑待确认
     *
     * @param share
     * @param nav
     * @param feeRate
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/12
     **/
    private static String calculateRedemptionFee(String share, String nav, String feeRate) {
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

    public static void main(String[] args) {
        System.out.println(calculatePurchaseFee("1000", "0.15%"));
        // 25.70
        System.err.println(calculateRedemptionFee("4193.84", "1.2252", "0.50%"));
    }
}
