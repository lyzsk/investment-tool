package cn.sichu.service;

import cn.sichu.entity.FundHistoryNav;

import java.io.IOException;
import java.text.ParseException;
import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/11
 **/
public interface IFundHistoryNavService {

    /**
     * @param code      code
     * @param startDate startDate
     * @param endDate   endDate
     * @param callback  callback
     * @author sichu huang
     * @date 2024/03/11
     **/
    void insertFundHistoryNav(String code, String startDate, String endDate, String callback)
        throws ParseException, IOException;

    /**
     * @param code code
     * @param date date
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/16
     **/
    String selectFundHistoryNavByConditions(String code, Date date);

    /**
     * @param code code
     * @return java.util.List<cn.sichu.entity.FundHistoryNav>
     * @author sichu huang
     * @date 2024/03/19
     **/
    List<FundHistoryNav> selectLastFundHistoryNavDateByConditions(String code);

    /**
     * @param code code
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/18
     **/
    String selectCallbackByCode(String code);

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    void updateHistoryNavByDate(Date date) throws ParseException, IOException;
}
