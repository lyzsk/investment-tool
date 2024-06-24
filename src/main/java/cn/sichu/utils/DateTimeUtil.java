package cn.sichu.utils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * @author sichu huang
 * @date 2024/06/10
 **/
public class DateTimeUtil {
    private static final DateTimeFormatter YYYY_MM_DD_HH_MM_SS = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    /**
     * @param str str
     * @return java.time.LocalDateTime
     * @author sichu huang
     * @date 2024/06/10
     **/
    public static LocalDateTime strToDateTime(String str) {
        return LocalDateTime.parse(str, YYYY_MM_DD_HH_MM_SS);
    }

    /**
     * @param dateTime dateTime
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/06/10
     **/
    public static String dateTimeToStr(LocalDateTime dateTime) {
        return dateTime.format(YYYY_MM_DD_HH_MM_SS);
    }

    /**
     * @param dateTime dateTime
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/06/10
     **/
    public static String localDateTimeToDateStr(LocalDateTime dateTime) {
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
        return dateTime.format(formatter);
    }

}
