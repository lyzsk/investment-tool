package cn.sichu.calc.vo;

import java.math.BigDecimal;

/**
 * @author sichu huang
 * @since 2026/02/15 18:49
 */
public record DaysToTargetVo(BigDecimal principal, BigDecimal targetAmount,
                             BigDecimal dailyReturnRate, int requiredTradingDays) {
}
