package utils;

import org.quartz.CronExpression;
import result.ResultCode;

import java.text.ParseException;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @since 2025/12/21 00:46
 */
public class CronUtils {
    /**
     * @param cronExpression cronExpression
     * @return boolean 是否有效
     * @author sichu huang
     * @since 2025/12/21 00:46:38
     */
    public static boolean isValid(String cronExpression) {
        return CronExpression.isValidExpression(cronExpression);
    }

    /**
     * 继续CRON表达式, 获得下 n 个满足执行的时间
     *
     * @param cronExpression cronExpression
     * @param n              数量
     * @return java.util.List<java.time.LocalDateTime> 满足条件的执行时间
     * @author sichu huang
     * @since 2025/12/21 00:55:17
     */
    public static List<LocalDateTime> getNextTimes(String cronExpression, int n) {
        try {
            CronExpression cron = new CronExpression(cronExpression);
            Date now = new Date();
            List<LocalDateTime> times = new ArrayList<>(n);
            for (int i = 0; i < n; i++) {
                Date next = cron.getNextValidTimeAfter(now);
                if (next == null)
                    break;
                times.add(LocalDateTime.ofInstant(next.toInstant(), ZoneId.systemDefault()));
                now = next;
            }
            return times;
        } catch (ParseException e) {
            throw new IllegalArgumentException(
                ResultCode.INVALID_CRON_EXPRESSION.getMsg() + ": " + cronExpression, e);
        }
    }
}
