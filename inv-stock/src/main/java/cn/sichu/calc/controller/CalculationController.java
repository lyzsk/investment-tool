package cn.sichu.calc.controller;

import cn.sichu.calc.vo.DaysToTargetVo;
import cn.sichu.calc.vo.FinalAmountVo;
import cn.sichu.calc.vo.TradingDayCountVo;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import result.Result;
import utils.DateTimeUtils;
import utils.TradingDayUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

/**
 * @author sichu huang
 * @since 2026/02/15 18:15
 */
@RestController
@RequestMapping("/api/calc")
@RequiredArgsConstructor
@Slf4j
public class CalculationController {

    /**
     * 两个日期之间(include start & end)的实际交易日数量
     *
     * @param start yyyy-MM-dd
     * @param end   yyyy-MM-dd
     * @return result.Result<cn.sichu.calc.vo.TradingDayCountVo> 包含起止日期和交易日数量的响应对象
     * @author sichu huang
     * @since 2026/02/15 18:55:13
     */
    @PostMapping("/count-trading-days")
    public Result<TradingDayCountVo> countTradingDays(
        @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate start,
        @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate end) {
        if (start == null || end == null) {
            return Result.fail("开始日期和结束日期不能为空");
        }
        if (start.isAfter(end)) {
            return Result.fail("开始日期不能晚于结束日期");
        }
        long totalDays = ChronoUnit.DAYS.between(start, end) + 1;
        if (totalDays > 365 * 5L) {
            return Result.fail("日期范围过大，请限制在5年内");
        }
        int tradingDays = 0;
        LocalDate current = start;
        while (!current.isAfter(end)) {
            if (TradingDayUtils.isTradingDay(current)) {
                tradingDays++;
            }
            current = current.plusDays(1);
        }
        TradingDayCountVo vo = new TradingDayCountVo(start.format(DateTimeUtils.YYYY_MM_DD),
            end.format(DateTimeUtils.YYYY_MM_DD), tradingDays);
        return Result.success(vo);
    }

    /**
     * 基于复利模型计算最终资产金额
     * <p/>
     * 公式：finalAmount = principal × (1 + dailyReturnRate)^tradingDays
     *
     * @param principal       本金(必须 > 0)
     * @param dailyReturnRate 日均收益率, 0.01表示1%, 取值范围 (-1, 1)
     * @param start           yyyy-MM-dd
     * @param end             yyyy-MM-dd
     * @return result.Result<cn.sichu.calc.vo.FinalAmountVo> 包含输入参数与最终资产金额的响应对象, 金额保留2位小数
     * @author sichu huang
     * @since 2026/02/15 18:51:19
     */
    @PostMapping("/final-amount")
    public Result<FinalAmountVo> calculateFinalAmount(@RequestParam BigDecimal principal,
        @RequestParam BigDecimal dailyReturnRate,
        @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate start,
        @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate end) {
        if (principal == null || principal.compareTo(BigDecimal.ZERO) <= 0) {
            return Result.fail("本金必须大于0");
        }
        if (dailyReturnRate == null || dailyReturnRate.compareTo(BigDecimal.ONE) >= 0
            || dailyReturnRate.compareTo(new BigDecimal("-1")) <= 0) {
            return Result.fail("日收益率必须在 (-1, 1) 区间内，例如 0.01 表示 1%");
        }
        Result<TradingDayCountVo> countResult = countTradingDays(start, end);
        if (!Result.isSuccess(countResult)) {
            return Result.fail(countResult.getMsg());
        }
        int tradingDays = countResult.getData().tradingDays();
        /* final = principal * (1 + r)^n */
        BigDecimal onePlusR = BigDecimal.ONE.add(dailyReturnRate);
        BigDecimal finalAmount = principal.multiply(onePlusR.pow(tradingDays));
        FinalAmountVo vo = new FinalAmountVo(principal, dailyReturnRate, tradingDays,
            finalAmount.setScale(2, RoundingMode.HALF_UP));
        return Result.success(vo);
    }

    /**
     * 计算达到目标资产金额所需的交易日数量(向上取整)
     * <p/>
     * 公式：requiredDays = ceil( log(targetAmount / principal) / log(1 + dailyReturnRate)
     *
     * @param principal       本金(必须 > 0)
     * @param targetAmount    目标资产金额(必需大于principal)
     * @param dailyReturnRate 日均收益率, 0.01表示1%
     * @return result.Result<cn.sichu.calc.vo.DaysToTargetVo>
     * @author sichu huang
     * @since 2026/02/15 19:04:35
     */
    @PostMapping("/days-to-target")
    public Result<DaysToTargetVo> calculateDaysToTarget(@RequestParam BigDecimal principal,
        @RequestParam BigDecimal targetAmount, @RequestParam BigDecimal dailyReturnRate) {
        if (principal == null || principal.compareTo(BigDecimal.ZERO) <= 0) {
            return Result.fail("本金必须大于0");
        }
        if (targetAmount == null || targetAmount.compareTo(principal) <= 0) {
            return Result.fail("目标金额必须大于本金");
        }
        if (dailyReturnRate == null || dailyReturnRate.compareTo(BigDecimal.ZERO) <= 0
            || dailyReturnRate.compareTo(BigDecimal.ONE) >= 0) {
            return Result.fail("日收益率必须在 (0, 1) 区间内，例如 0.01 表示 1%");
        }
        /* n = log(target / principal) / log(1 + r) */
        double ratio = targetAmount.divide(principal, 10, RoundingMode.HALF_UP).doubleValue();
        double onePlusR = 1.0 + dailyReturnRate.doubleValue();
        double days = Math.log(ratio) / Math.log(onePlusR);
        int requiredDays = (int)Math.ceil(days);
        DaysToTargetVo vo =
            new DaysToTargetVo(principal, targetAmount, dailyReturnRate, requiredDays);
        return Result.success(vo);
    }

    /**
     * @param principal       本金
     * @param dailyReturnRate 日均收益率, 0.01表示1%, 取值范围 (0, 1)
     * @param targetAmount    目标资产金额(必须大于本金)
     * @param start           yyyy-MM-dd
     * @return result.Result<java.lang.String>
     * @author sichu huang
     * @since 2026/02/15 19:34:38
     */
    @PostMapping("/date-to-target")
    public Result<String> calculateDateToTarget(@RequestParam BigDecimal principal,
        @RequestParam BigDecimal dailyReturnRate, @RequestParam BigDecimal targetAmount,
        @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate start) {
        if (principal == null || principal.compareTo(BigDecimal.ZERO) <= 0) {
            return Result.fail("本金必须大于0");
        }
        if (targetAmount == null || targetAmount.compareTo(principal) <= 0) {
            return Result.fail("目标金额必须大于本金");
        }
        if (dailyReturnRate == null || dailyReturnRate.compareTo(BigDecimal.ZERO) <= 0
            || dailyReturnRate.compareTo(BigDecimal.ONE) >= 0) {
            return Result.fail("日收益率必须在 (0, 1) 区间内，例如 0.01 表示 1%");
        }
        if (start == null) {
            return Result.fail("起始日期不能为空");
        }
        double ratio = targetAmount.divide(principal, 10, RoundingMode.HALF_UP).doubleValue();
        double onePlusR = 1.0 + dailyReturnRate.doubleValue();
        double days = Math.log(ratio) / Math.log(onePlusR);
        int requiredTradingDays = (int)Math.ceil(days);
        LocalDate current = start;
        int counted = 0;
        while (counted < requiredTradingDays) {
            if (TradingDayUtils.isTradingDay(current)) {
                counted++;
                if (counted == requiredTradingDays) {
                    break;
                }
            }
            current = current.plusDays(1);
        }
        String targetDateStr = current.format(DateTimeUtils.YYYY_MM_DD);
        return Result.success(targetDateStr);
    }
}
