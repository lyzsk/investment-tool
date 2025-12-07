package utils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * @author sichu huang
 * @since 2025/12/07 03:16
 */
public class DateUtils {
    public static final DateTimeFormatter YYYY_MM_DD_HH_MM_SS_SSSSSS =
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss:SSSSSS");
    public static final DateTimeFormatter YYYYMMDDHHMMSSSSSSSS =
        DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSSSSS");
    public static final DateTimeFormatter YYYYMMDD_DOT = DateTimeFormatter.ofPattern("yyyy.MM.dd");

    /**
     * @param localDateTime LocalDateTime.now()
     * @return java.lang.String 返回 yyyy-MM-dd HH:mm:ss:SSSSSS 格式的当前时间字符串
     * @author sichu huang
     * @since 2025/12/07 03:41:12
     */
    public static String getMillionSecondStr(LocalDateTime localDateTime) {
        return localDateTime.format(YYYY_MM_DD_HH_MM_SS_SSSSSS);
    }

    /**
     * @return java.lang.String 返回 yyyyMMddHHmmssSSSSSS 格式的当前时间字符串
     * @author sichu huang
     * @since 2025/12/07 21:41:51
     */
    public static String getNumericMillionSecondStr() {
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

}
