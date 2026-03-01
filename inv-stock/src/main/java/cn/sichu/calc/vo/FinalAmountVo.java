package cn.sichu.calc.vo;

import java.math.BigDecimal;

/**
 * @author sichu huang
 * @since 2026/02/15 18:48
 */
public record FinalAmountVo(BigDecimal principal, BigDecimal dailyReturnRate, int tradingDays,
                            BigDecimal finalAmount) {
}
