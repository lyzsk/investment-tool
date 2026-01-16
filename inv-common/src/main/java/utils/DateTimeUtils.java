package utils;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * @author sichu huang
 * @since 2025/12/07 03:16
 */
public class DateTimeUtils {
    /**
     * yyyy-MM-dd
     */
    public static final DateTimeFormatter YYYY_MM_DD = DateTimeFormatter.ofPattern("yyyy-MM-dd");
    /**
     * HH:mm:ss
     */
    public static final DateTimeFormatter HH_MM_SS = DateTimeFormatter.ofPattern("HH:mm:ss");
    /**
     * yyyy-MM-dd HH:mm:ss
     */
    public static final DateTimeFormatter YYYY_MM_DD_HH_MM_SS =
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    /**
     * M月d日
     */
    public static final DateTimeFormatter M_D_CHINESE = DateTimeFormatter.ofPattern("M月d日");
    /**
     * yyyy.MM.dd
     */
    public static final DateTimeFormatter YYYYMMDD_DOT = DateTimeFormatter.ofPattern("yyyy.MM.dd");
    /**
     * yyyyMMddHHmmss
     */
    public static final DateTimeFormatter YYYYMMDDHHMMSS =
        DateTimeFormatter.ofPattern("yyyyMMddHHmmss");
    /**
     * yyyyMMddHHmmssSSSSSS
     */
    public static final DateTimeFormatter YYYYMMDDHHMMSSSSSSSS =
        DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSSSSS");
    /**
     * yyyy-MM-dd HH:mm:ss:SSSSSS
     */
    public static final DateTimeFormatter YYYY_MM_DD_HH_MM_SS_SSSSSS =
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss:SSSSSS");

    /**
     * @param localDateTime LocalDateTime.now()
     * @return java.lang.String 返回 yyyy-MM-dd HH:mm:ss:SSSSSS 格式的当前时间字符串
     * @author sichu huang
     * @since 2025/12/07 03:41:12
     */
    public static String getNanoSecondStr(LocalDateTime localDateTime) {
        return localDateTime.format(YYYY_MM_DD_HH_MM_SS_SSSSSS);
    }

    /**
     * @return java.lang.String 返回 yyyyMMddHHmmssSSSSSS 格式的当前时间字符串
     * @author sichu huang
     * @since 2025/12/07 21:41:51
     */
    public static String getNumericNanoSecondStr() {
        return LocalDateTime.now().format(YYYYMMDDHHMMSSSSSSSS);
    }

    /**
     * @return java.lang.String 返回 yyyy.MM.dd 格式的当前日期字符串
     * @author sichu huang
     * @since 2025/12/07 03:30:41
     */
    public static String getDotDateStr() {
        return LocalDateTime.now().format(YYYYMMDD_DOT);
    }

    /**
     * @param dateTime LocalDateTime
     * @return java.lang.String 返回 yyyy.MM.dd 格式的当前日期字符串
     * @author sichu huang
     * @since 2026/01/05 16:26:24
     */
    public static String getDotDateStr(LocalDateTime dateTime) {
        return dateTime.toLocalDate().format(YYYYMMDD_DOT);
    }

    /**
     * @param dateTime LocalDateTime
     * @return java.lang.String 返回 yyyyMMddHHmmss 格式的当前日期字符串
     * @author sichu huang
     * @since 2026/01/06 16:10:03
     */
    public static String getSecondStr(LocalDateTime dateTime) {
        return dateTime.format(YYYYMMDDHHMMSS);
    }

    /**
     * LocalDate 转为中文星期
     *
     * @param date LocalDate
     * @return java.lang.String 周一/周二/周三/周四/周五/周六/周日
     * @author sichu huang
     * @since 2026/01/14 12:57:10
     */
    public static String getDayOfWeekCN(LocalDate date) {
        return switch (date.getDayOfWeek()) {
            case MONDAY -> "周一";
            case TUESDAY -> "周二";
            case WEDNESDAY -> "周三";
            case THURSDAY -> "周四";
            case FRIDAY -> "周五";
            case SATURDAY -> "周六";
            case SUNDAY -> "周日";
        };
    }

    /**
     * e.g. 2026-01-15 -> 2026S1
     *
     * @param date LocalDate
     * @return java.lang.String year+S+quarter
     * @author sichu huang
     * @since 2026/01/15 23:58:04
     */
    public static String getQuarterStr(LocalDate date) {
        int year = date.getYear();
        int month = date.getMonthValue();
        int quarter = (month - 1) / 3 + 1;
        return year + "S" + quarter;
    }
}
