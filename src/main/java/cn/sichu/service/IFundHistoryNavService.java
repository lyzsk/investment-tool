package cn.sichu.service;

import java.io.IOException;
import java.text.ParseException;

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
}
