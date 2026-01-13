import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import utils.TradingDayUtils;

import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * @author sichu huang
 * @since 2026/01/12 16:58
 */
public class TradingDayUtilsTest {
    @Test
    @DisplayName("2026-01-12 是周一，非节假日 → 应为交易日")
    void testNormalTradingDay() {
        LocalDate date = LocalDate.of(2026, 1, 12); // 星期一
        assertTrue(TradingDayUtils.isTradingDay(date));
    }

    @Test
    @DisplayName("2026-01-01 是元旦（周四），应为节假日 → 非交易日")
    void testNewYearHoliday() {
        LocalDate date = LocalDate.of(2026, 1, 1);
        assertFalse(TradingDayUtils.isTradingDay(date));
    }

    @Test
    @DisplayName("2026-01-11 是周日 → 非交易日（即使调休上班）")
    void testWeekendSunday() {
        LocalDate date = LocalDate.of(2026, 1, 11); // Sunday
        assertFalse(TradingDayUtils.isTradingDay(date));
    }

    @Test
    @DisplayName("2026-01-10 是周六 → 非交易日")
    void testWeekendSaturday() {
        LocalDate date = LocalDate.of(2026, 1, 10); // Saturday
        assertFalse(TradingDayUtils.isTradingDay(date));
    }

    @Test
    @DisplayName("2025-10-09 是国庆节后首个工作日（周四）→ 应为交易日")
    void testAfterNationalDay() {
        LocalDate date = LocalDate.of(2025, 10, 9);
        assertTrue(TradingDayUtils.isTradingDay(date));
    }

    @Test
    @DisplayName("null 输入应返回 false")
    void testNullInput() {
        assertFalse(TradingDayUtils.isTradingDay(null));
    }
}
