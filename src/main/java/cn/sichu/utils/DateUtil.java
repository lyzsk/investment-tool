package cn.sichu.utils;

import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Date;

/**
 * @author sichu huang
 * @date 2024/03/18
 **/
public class DateUtil {
    private static final SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd");

    /**
     * @param date date
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/19
     **/
    public static String dateToStr(Date date) {
        Date newDate = new Date(date.getTime());
        return sdf.format(newDate);
    }

    /**
     * @param date date
     * @return java.util.Date
     * @author sichu huang
     * @date 2024/03/19
     **/
    public static Date strToDate(String date) throws ParseException {
        return sdf.parse(date);
    }

    /**
     * @param date date
     * @return java.util.Date
     * @author sichu huang
     * @date 2024/03/19
     **/
    public static Date formatDate(Date date) throws ParseException {
        return sdf.parse(sdf.format(date));
    }

    /**
     * @param date date
     * @return java.util.Date
     * @author sichu huang
     * @date 2024/04/07
     **/
    public static Date formatDate(String date) throws ParseException {
        return formatDate(strToDate(date));
    }
}
