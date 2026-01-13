package utils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * @author sichu huang
 * @since 2025/12/07 03:16
 */
public class DateTimeUtils {
    public static final DateTimeFormatter YYYY_MM_DD_HH_MM_SS_SSSSSS =
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss:SSSSSS");
    public static final DateTimeFormatter YYYYMMDDHHMMSSSSSSSS =
        DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSSSSS");
    public static final DateTimeFormatter YYYYMMDD_DOT = DateTimeFormatter.ofPattern("yyyy.MM.dd");
    public static final DateTimeFormatter YYYYMMDDHHMMSS =
        DateTimeFormatter.ofPattern("yyyyMMddHHmmss");

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

}
