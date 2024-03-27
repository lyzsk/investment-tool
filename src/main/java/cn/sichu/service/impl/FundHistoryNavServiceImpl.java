package cn.sichu.service.impl;

import cn.sichu.entity.FundEastmoneyJjjz;
import cn.sichu.entity.FundHistoryNav;
import cn.sichu.exception.FundTransactionException;
import cn.sichu.mapper.FundEastmoneyJjjzMapper;
import cn.sichu.mapper.FundHistoryNavMapper;
import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.utils.DateUtil;
import cn.sichu.utils.ScrapingUtil;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.text.ParseException;
import java.util.ArrayList;
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
     * @param code      code
     * @param startDate startDate
     * @param endDate   endDate
     * @param callback  callback
     * @author sichu huang
     * @date 2024/03/11
     **/
    @Override
    public void insertFundHistoryNav(String code, String startDate, String endDate, String callback) throws ParseException, IOException {
        Map<String, String> map = ScrapingUtil.getDailyNavMapBetweenDates(code, startDate, endDate, callback);
        for (Map.Entry<String, String> entry : map.entrySet()) {
            Date navDate = DateUtil.strToDate(entry.getKey());
            String nav = entry.getValue();
            FundHistoryNav fundHistoryNav = new FundHistoryNav();
            fundHistoryNav.setCode(code);
            fundHistoryNav.setNavDate(navDate);
            fundHistoryNav.setNav(nav);
            fundHistoryNavMapper.insertFundHistoryNav(fundHistoryNav);
        }
    }

    /**
     * @param code    code
     * @param navDate navDate
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/16
     **/
    @Override
    public String selectFundHistoryNavOrderByConditions(String code, Date navDate) throws ParseException, IOException {
        List<FundHistoryNav> fundHistoryNavs = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
        if (!fundHistoryNavs.isEmpty()) {
            return fundHistoryNavs.get(0).getNav();
        }
        String navStr;
        String callback = selectCallbackByCode(code);
        List<FundHistoryNav> historyNavs = selectLastFundHistoryNavDateByCode(code);
        if (historyNavs.isEmpty()) {
            navStr = retryUpdateHistoryNav(code, navDate);
            if (navStr == null || navStr.equals("")) {
                throw new FundTransactionException(999, "更新历史净值失败");
            }
            historyNavs = fundHistoryNavMapper.selectLastFundHistoryNavDates();
        }
        Date lastNavDate = historyNavs.get(0).getNavDate();
        if (navDate.getTime() >= lastNavDate.getTime()) {
            insertFundHistoryNav(code, DateUtil.dateToStr(lastNavDate), DateUtil.dateToStr(navDate), callback);
            List<FundHistoryNav> updatedHistoryNavs = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
            if (updatedHistoryNavs.isEmpty()) {
                /* 净值未更新 */
                return "";
            } else {
                return updatedHistoryNavs.get(0).getNav();
            }
        } else {
            navStr = retryUpdateHistoryNav(code, navDate);
            if (navStr == null || navStr.equals("")) {
                throw new FundTransactionException(999, "更新历史净值失败");
            }
        }
        return navStr;
    }

    /**
     * @param code code
     * @return java.util.List<cn.sichu.entity.FundHistoryNav>
     * @author sichu huang
     * @date 2024/03/19
     **/
    @Override
    public List<FundHistoryNav> selectLastFundHistoryNavDateByCode(String code) {
        return fundHistoryNavMapper.selectLastFundHistoryNavDateByCode(code);
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

    /**
     * @return java.util.List<java.lang.String>
     * @author sichu huang
     * @date 2024/03/25
     **/
    @Override
    public List<String> selectAllCode() {
        List<FundHistoryNav> fundHistoryNavs = fundHistoryNavMapper.selectAllCode();
        List<String> list = new ArrayList<>();
        for (FundHistoryNav fundHistoryNav : fundHistoryNavs) {
            list.add(fundHistoryNav.getCode());
        }
        return list;
    }

    /**
     * @param code code
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    @Override
    public void updateHistoryNavByCodeAndDate(String code, Date date) throws ParseException, IOException {
        List<FundHistoryNav> fundHistoryNavs = fundHistoryNavMapper.selectLastFundHistoryNavDates();
        String callback = selectCallbackByCode(code);
        if (fundHistoryNavs.isEmpty()) {
            String navStr = retryUpdateHistoryNav(code, date);
            if (navStr == null || navStr.equals("")) {
                throw new FundTransactionException(999, "更新历史净值失败");
            }
            fundHistoryNavs = fundHistoryNavMapper.selectLastFundHistoryNavDates();
        }
        FundHistoryNav historyNav = fundHistoryNavs.get(0);
        Date lastNavDate = historyNav.getNavDate();
        if (date.getTime() >= lastNavDate.getTime()) {
            insertFundHistoryNav(code, DateUtil.dateToStr(lastNavDate), DateUtil.dateToStr(date), callback);
        } else {
            throw new FundTransactionException(999, "更新日期应大于历史净值最大日期");
        }
    }

    /**
     * @param code    code
     * @param navDate navDate
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/27
     **/
    private String retryUpdateHistoryNav(String code, Date navDate) throws IOException, ParseException {
        String callback = selectCallbackByCode(code);
        String navStr = null;
        int tryCount = 3;
        for (int i = 0; i <= tryCount; i++) {
            if (navStr != null && !navStr.equals("")) {
                break;
            }
            Date date;
            switch (i) {
                case 0 -> date = TransactionDayUtil.getLastNTransactionDate(navDate, 7);
                case 1 -> date = TransactionDayUtil.getLastNTransactionDate(navDate, 30);
                case 2 -> date = TransactionDayUtil.getLastNTransactionDate(navDate, 90);
                default -> date = DateUtil.strToDate("2023-08-01");
            }
            insertFundHistoryNav(code, DateUtil.dateToStr(date), DateUtil.dateToStr(navDate), callback);
            navStr = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate).get(0).getNav();
        }
        return navStr;
    }
}
