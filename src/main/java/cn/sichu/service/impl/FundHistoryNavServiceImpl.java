package cn.sichu.service.impl;

import cn.sichu.entity.FundEastmoneyJjjz;
import cn.sichu.entity.FundHistoryNav;
import cn.sichu.mapper.FundEastmoneyJjjzMapper;
import cn.sichu.mapper.FundHistoryNavMapper;
import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.utils.DateUtil;
import cn.sichu.utils.ScrapingUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.text.ParseException;
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
    public String selectFundHistoryNavOrderByConditions(String code, Date navDate) {
        List<FundHistoryNav> fundHistoryNavs = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
        if (fundHistoryNavs.isEmpty()) {
            return "";
        }
        return fundHistoryNavs.get(0).getNav();
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
        return fundHistoryNavMapper.selectAllCode();
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
        FundHistoryNav historyNav = fundHistoryNavs.get(0);
        String callback = selectCallbackByCode(code);
        Date lastNavDate = historyNav.getNavDate();
        if (date.getTime() >= lastNavDate.getTime()) {
            insertFundHistoryNav(code, DateUtil.dateToStr(lastNavDate), DateUtil.dateToStr(date), callback);
        }
    }
}
