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

    public static String dateToStr(Date date) {
        Date newDate = new Date(date.getTime());
        return sdf.format(newDate);
    }

    public static Date strToDate(String date) throws ParseException {
        return sdf.parse(date);
    }
}
