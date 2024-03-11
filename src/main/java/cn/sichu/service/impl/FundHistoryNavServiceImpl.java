package cn.sichu.service.impl;

import cn.sichu.entity.FundHistoryNav;
import cn.sichu.mapper.FundHistoryNavMapper;
import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.utils.JsoupUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Map;

/**
 * @author sichu huang
 * @date 2024/03/11
 **/
@Service
public class FundHistoryNavServiceImpl implements IFundHistoryNavService {
    @Autowired
    private FundHistoryNavMapper fundHistoryNavMapper;

    /**
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
        Map<String, String> map = JsoupUtil.getDailyNavMapBetweenDates(code, startDate, endDate, callback);
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
}
