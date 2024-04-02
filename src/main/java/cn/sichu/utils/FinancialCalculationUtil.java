package cn.sichu.utils;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * @author sichu huang
 * @date 2024/03/12
 **/
public class FinancialCalculationUtil {

    /**
     * 净申购金额 = 申购金额 / (1+申购费率)
     * <br/>
     * 申购费用 = 申购金额 - 净申购金额
     * <br/>
     * 净申购份额 = 净申购金额 / 申购当日基金单位净值
     * <br/>
     * 注: 净申购金额及申购份数的计算结果以四舍五入的方法保留小数点后两位
     *
     * @param amount amount
     * @param fee    fee
     * @param nav    nav
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/18
     **/
    public static BigDecimal calculateShare(BigDecimal amount, BigDecimal fee, String nav) {
        BigDecimal netAmount = amount.subtract(fee);
        return netAmount.divide(new BigDecimal(nav), 2, RoundingMode.HALF_UP);
    }

    /**
     * 净申购金额 = 申购金额 / (1+申购费率)
     * <br/>
     * 申购费用 = 申购金额 - 净申购金额
     * <br/>
     * 净申购份额 = 净申购金额 / 申购当日基金单位净值
     * <br/>
     * 注: 净申购金额及申购份数的计算结果以四舍五入的方法保留小数点后两位
     *
     * @param amount  amount
     * @param feeRate feeRate
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/18
     **/
    public static BigDecimal calculatePurchaseFee(BigDecimal amount, String feeRate) {
        String rate = feeRate.replace("%", "");
        BigDecimal netAmount =
            amount.divide(new BigDecimal("1").add(new BigDecimal(rate).divide(new BigDecimal("100"), 6, RoundingMode.HALF_UP)), 2,
                RoundingMode.HALF_UP);
        return amount.subtract(netAmount).setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * 赎回费用 = 赎回当日基金单位净值 * 赎回份额 * 赎回费率
     * <br/>
     * 赎回金额 = 赎回当日基金单位净值 * 赎回份额 -赎回费用
     *
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
        BigDecimal r = new BigDecimal(rate).divide(new BigDecimal("100"), 6, RoundingMode.HALF_UP);
        return n.multiply(share).multiply(r).setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * 赎回费用 = 赎回当日基金单位净值 * 赎回份额 * 赎回费率
     * <br/>
     * 赎回金额 = 赎回当日基金单位净值 * 赎回份额 -赎回费用
     *
     * @param share share
     * @param nav   nav
     * @param fee   fee
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/25
     **/
    public static BigDecimal calculateRedemptionAmount(BigDecimal share, String nav, BigDecimal fee) {
        BigDecimal n = new BigDecimal(nav);
        return share.multiply(n).subtract(fee).setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * @param share share
     * @param nav   nav
     * @param fee   fee
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/03/31
     **/
    public static BigDecimal calculateAmount(BigDecimal share, String nav, BigDecimal fee) {
        return share.multiply(new BigDecimal(nav)).subtract(fee).setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * 摊薄单价 = (合计本金 - 合计买入手续费) / 合计份额
     *
     * @param amount 合计本金
     * @param fee    合计买入手续费
     * @param share  合计份额
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/04/02
     **/
    public static BigDecimal calculateDilutedNav(BigDecimal amount, BigDecimal fee, BigDecimal share) {
        return amount.subtract(fee).divide(share, 4, RoundingMode.HALF_UP);
    }

    /**
     * 成本均价 = 合计本金 / 合计份额
     *
     * @param amount 合计本金
     * @param share  合计份额
     * @return java.math.BigDecimal
     * @author sichu huang
     * @date 2024/04/02
     **/
    public static BigDecimal calculateAvgNavPerShare(BigDecimal amount, BigDecimal share) {
        return amount.divide(share, 4, RoundingMode.HALF_UP);
    }
}
