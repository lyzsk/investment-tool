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
     * @param code
     * @param startDate
     * @param endDate
     * @param callback
     * @author sichu huang
     * @date 2024/03/11
     **/
    public void insertFundHistoryNavInformation(String code, String startDate, String endDate, String callback)
        throws ParseException, IOException;

    /**
     * @param code
     * @param date
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/13
     **/
    public String selectFundHistoryNavByConditions(String code, String date) throws ParseException;

    /**
     * @param code code
     * @return java.util.List<cn.sichu.entity.FundHistoryNav>
     * @author sichu huang
     * @date 2024/03/19
     **/
    public List<FundHistoryNav> selectLastFundHistoryNavDateByConditions(String code);

    /**
     * @param code
     * @param date
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/16
     **/
    public String selectFundHistoryNavByConditions(String code, Date date);

    /**
     * @param code code
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/18
     **/
    public String selectCallbackByCode(String code);
}
