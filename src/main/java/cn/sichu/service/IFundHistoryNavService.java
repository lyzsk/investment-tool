package cn.sichu.service;

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
    void insertFundHistoryNav(String code, String startDate, String endDate, String callback) throws ParseException, IOException;

    /**
     * @param code    code
     * @param navDate navDate
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/16
     **/
    String selectFundNavByConditions(String code, Date navDate) throws ParseException, IOException;

    /**
     * @param code code
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/18
     **/
    String selectCallbackByCode(String code);

    /**
     * @return java.util.List<java.lang.String>
     * @author sichu huang
     * @date 2024/05/05
     **/
    List<String> selectAllCode();

    /**
     * @return java.util.List<java.lang.String>
     * @author sichu huang
     * @date 2024/03/25
     **/
    List<String> selectAllHeldCode();

    /**
     * @param code code
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/05/05
     **/
    String selectLastHistoryNav(String code);

    /**
     * 根据 1.code, 2.navDate 更新 `fund_history_nav`
     *
     * @param code code
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    void updateHistoryNavByConditions(String code, Date date) throws ParseException, IOException;

}
