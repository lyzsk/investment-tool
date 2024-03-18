package cn.sichu.service.impl;

import cn.sichu.entity.FundEastmoneyJjjz;
import cn.sichu.entity.FundHistoryNav;
import cn.sichu.mapper.FundEastmoneyJjjzMapper;
import cn.sichu.mapper.FundHistoryNavMapper;
import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.utils.ScrapingUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Map;

/**
 * @author sichu huang
 * @date 2024/03/11
 **/
@Service
public class FundHistoryNavServiceImpl implements IFundHistoryNavService {
    @Autowired
    FundHistoryNavMapper fundHistoryNavMapper;
    @Autowired
    FundEastmoneyJjjzMapper fundEastmoneyJjjzMapper;

    /**
     * 插入历史净值, 如果净值日期在表中已存在不会重复插入
     *
     * @param code
     * @param startDate
     * @param endDate
     * @param callback
     * @author sichu huang
     * @date 2024/03/11
     **/
    @Override
    public void insertFundHistoryNavInformation(String code, String startDate, String endDate, String callback)
        throws ParseException, IOException {
        Map<String, String> map = ScrapingUtil.getDailyNavMapBetweenDates(code, startDate, endDate, callback);
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd");
        for (Map.Entry<String, String> entry : map.entrySet()) {
            String navDateStr = entry.getKey();
            java.sql.Date navDate = new java.sql.Date(sdf.parse(navDateStr).getTime());
            String nav = entry.getValue();
            FundHistoryNav fundHistoryNav = new FundHistoryNav();
            fundHistoryNav.setCode(code);
            fundHistoryNav.setNavDate(navDate);
            fundHistoryNav.setNav(nav);
            fundHistoryNavMapper.insertFundHistoryNavInformation(fundHistoryNav);
        }
    }

    /**
     * @param code
     * @param date
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/13
     **/
    @Override
    public String selectFundHistoryNavByConditions(String code, String date) throws ParseException {
        String nav = "";
        FundHistoryNav fundHistoryNav = new FundHistoryNav();
        fundHistoryNav.setCode(code);
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd");
        Date parsedDate = sdf.parse(date);
        fundHistoryNav.setNavDate(parsedDate);
        List<FundHistoryNav> fundHistoryNavs = fundHistoryNavMapper.selectFundHistoryNavByConditions(fundHistoryNav);
        for (FundHistoryNav historyNav : fundHistoryNavs) {
            if (isSameDate(historyNav.getNavDate(), parsedDate)) {
                nav = historyNav.getNav();
                return nav;
            }
        }
        return "";
    }

    /**
     * @param code
     * @param date
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/16
     **/
    @Override
    public String selectFundHistoryNavByConditions(String code, Date date) {
        String nav;
        FundHistoryNav fundHistoryNav = new FundHistoryNav();
        fundHistoryNav.setCode(code);
        fundHistoryNav.setNavDate(date);
        List<FundHistoryNav> fundHistoryNavs = fundHistoryNavMapper.selectFundHistoryNavByConditions(fundHistoryNav);
        for (FundHistoryNav historyNav : fundHistoryNavs) {
            if (isSameDate(historyNav.getNavDate(), date)) {
                nav = historyNav.getNav();
                return nav;
            }
        }
        return "";
    }

    /**
     * @param code code
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/18
     **/
    @Override
    public String selectCallbackByCode(String code) {
        List<FundEastmoneyJjjz> list = fundEastmoneyJjjzMapper.selectCallbackByCode(code);
        return list.get(0).getCallback();
    }

    private boolean isSameDate(Date dbDate, Date date) {
        Calendar cal1 = Calendar.getInstance();
        cal1.setTime(dbDate);
        Calendar cal2 = Calendar.getInstance();
        cal2.setTime(date);
        return cal1.get(Calendar.YEAR) == cal2.get(Calendar.YEAR) && cal1.get(Calendar.MONTH) == cal2.get(
            Calendar.MONTH) && cal1.get(Calendar.DAY_OF_MONTH) == cal2.get(Calendar.DAY_OF_MONTH);
    }
}
