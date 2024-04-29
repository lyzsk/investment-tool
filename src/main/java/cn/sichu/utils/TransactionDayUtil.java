package cn.sichu.utils;

import org.json.JSONObject;

import java.io.IOException;
import java.text.ParseException;
import java.util.Date;
import java.util.concurrent.TimeUnit;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public class TransactionDayUtil {
    /**
     * @param date date
     * @return boolean
     * @author sichu huang
     * @date 2024/03/09
     * @see "https://stackoverflow.com/questions/4308554/simplest-way-to-read-json-from-a-url-in-java"
     * <br/>
     * "https://github.com/Dreace/ChinaHolidayAPI?tab=readme-ov-file"
     **/
    public static boolean isTransactionDate(Date date) throws IOException {
        String dateStr = DateUtil.dateToStr(date);
        JSONObject json = JsonUtil.readJsonFromUrl("https://holiday.dreace.top?date=" + dateStr);
        return json.get("note").equals("普通工作日");
    }

    /**
     * @param date
     * @return java.util.Date
     * @author sichu huang
     * @date 2024/03/10
     **/
    public static Date getNextTransactionDate(Date date) throws IOException {
        Date newDate = new Date(date.getTime());
        do {
            newDate.setTime(newDate.getTime() + 24 * 60 * 60 * 1000L);
        } while (!isTransactionDate(newDate));
        return newDate;
    }

    /**
     * @param date
     * @param n
     * @return java.util.Date
     * @author sichu huang
     * @date 2024/03/10
     **/
    public static Date getNextNTransactionDate(Date date, Integer n) throws IOException {
        Date newDate = new Date(date.getTime());
        int count = 0;
        while (count < n) {
            newDate.setTime(newDate.getTime() + 24 * 60 * 60 * 1000L);
            if (isTransactionDate(newDate)) {
                ++count;
            }
        }
        return newDate;
    }

    /**
     * @param date
     * @param n
     * @return java.util.Date
     * @author sichu huang
     * @date 2024/03/18
     **/
    public static Date getLastNTransactionDate(Date date, Integer n) throws IOException {
        Date newDate = new Date(date.getTime());
        int count = 0;
        while (count < n) {
            newDate.setTime(newDate.getTime() - 24 * 60 * 60 * 1000L);
            if (isTransactionDate(newDate)) {
                ++count;
            }
        }
        return newDate;
    }

    /**
     * @param startDate startDate
     * @param endDate   endDate
     * @return java.lang.Long
     * @author sichu huang
     * @date 2024/03/12
     **/
    public static Long getHeldDays(Date startDate, Date endDate) {
        long diff = endDate.getTime() - startDate.getTime();
        return TimeUnit.DAYS.convert(diff, TimeUnit.MILLISECONDS);
    }

    /**
     * @param mark mark
     * @return java.lang.Long
     * @author sichu huang
     * @date 2024/03/25
     **/
    public static Long getHeldDays(String mark) throws ParseException {
        String[] dates = mark.split("->");
        Date startDate = DateUtil.strToDate(dates[0]);
        Date endDate = DateUtil.strToDate(dates[1]);
        return getHeldDays(startDate, endDate);
    }

    /**
     * @param startDate
     * @param endDate
     * @return java.lang.Long
     * @author sichu huang
     * @date 2024/04/04
     **/
    public static long getHeldDays(String startDate, String endDate) throws ParseException {
        Date date1 = DateUtil.strToDate(startDate);
        Date date2 = DateUtil.strToDate(endDate);
        long diff = date2.getTime() - date1.getTime();
        return TimeUnit.DAYS.convert(diff, TimeUnit.MILLISECONDS);
    }

    /**
     * @param startDate
     * @param endDate
     * @return java.lang.Long
     * @author sichu huang
     * @date 2024/03/12
     **/
    public static Long getHeldTransactionDays(Date startDate, Date endDate) throws IOException {
        long heldTransactionDays = 0;
        long startTime = startDate.getTime();
        long endTime = endDate.getTime();
        while (startTime < endTime) {
            long tempTime = startTime + 24 * 60 * 60 * 1000L;
            Date tempDate = new Date(tempTime);
            if (isTransactionDate(tempDate)) {
                ++heldTransactionDays;
            }
            startTime = tempTime;
        }
        return heldTransactionDays;
    }

}
