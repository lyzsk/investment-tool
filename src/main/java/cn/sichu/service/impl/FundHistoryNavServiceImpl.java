package cn.sichu.service.impl;

import cn.sichu.entity.FundEastmoneyJjjz;
import cn.sichu.entity.FundHistoryNav;
import cn.sichu.exception.FundTransactionException;
import cn.sichu.mapper.FundEastmoneyJjjzMapper;
import cn.sichu.mapper.FundHistoryNavMapper;
import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.utils.CrawlUtil;
import cn.sichu.utils.DateUtil;
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

    @Override
    public void insertFundHistoryNav(String code, String startDate, String endDate, String callback) throws ParseException, IOException {
        Map<String, String> map = CrawlUtil.getDailyNavMapBetweenDates(code, startDate, endDate, callback);
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

    @Override
    public String selectFundNavByConditions(String code, Date navDate) throws ParseException, IOException {
        List<FundHistoryNav> fundHistoryNavList = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
        if (!fundHistoryNavList.isEmpty()) {
            return fundHistoryNavList.get(0).getNav();
        }
        String navStr;
        String callback = selectCallbackByCode(code);
        List<FundHistoryNav> historyNavList = selectLastFundHistoryNavDateByCode(code);
        if (historyNavList.isEmpty()) {
            navStr = retryUpdateHistoryNav(code, navDate);
            if (navStr == null || navStr.equals("")) {
                throw new FundTransactionException(999, "update history nav failed, because there is no history nav for this code");
            }
            historyNavList = fundHistoryNavMapper.selectLastFundHistoryNavDateAndNav();
        }
        Date lastNavDate = historyNavList.get(0).getNavDate();
        if (navDate.compareTo(lastNavDate) >= 0) {
            insertFundHistoryNav(code, DateUtil.dateToStr(lastNavDate), DateUtil.dateToStr(navDate), callback);
            List<FundHistoryNav> updatedHistoryNavList = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
            if (updatedHistoryNavList.isEmpty()) {
                /* 净值未更新 */
                return "";
            } else {
                return updatedHistoryNavList.get(0).getNav();
            }
        }
        // TODO: 没懂这里的意义, 先注释掉
        // else {
        //     navStr = retryUpdateHistoryNav(code, navDate);
        //     if (navStr == null || navStr.equals("")) {
        //         throw new FundTransactionException(999, "update history nav failed");
        //     }
        // }
        return "";
    }

    @Override
    public String selectLastNotNullFundHistoryNavByConditions(String code, Date navDate) throws ParseException, IOException {
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
            historyNavs = fundHistoryNavMapper.selectLastFundHistoryNavDateAndNav();
        }
        Date lastNavDate = historyNavs.get(0).getNavDate();
        if (navDate.getTime() >= lastNavDate.getTime()) {
            insertFundHistoryNav(code, DateUtil.dateToStr(lastNavDate), DateUtil.dateToStr(navDate), callback);
            List<FundHistoryNav> updatedHistoryNavs = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
            if (updatedHistoryNavs.isEmpty()) {
                /* 净值未更新, 缺少美股节假日, 暂时使用暴力解决 */
                navStr = null;
                int n = 1;
                int tryCount = 30;
                for (int i = 0; i <= tryCount; i++) {
                    if (navStr != null) {
                        return navStr;
                    }
                    navStr = selectFundNavByConditions(code, TransactionDayUtil.getLastNTransactionDate(navDate, ++n));
                    if (navStr == null || navStr.equals("")) {
                        throw new FundTransactionException(999, "暴力查净值失败");
                    }
                }
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

    @Override
    public List<FundHistoryNav> selectLastFundHistoryNavDateByCode(String code) {
        return fundHistoryNavMapper.selectLastFundHistoryNavDateByCode(code);
    }

    @Override
    public String selectCallbackByCode(String code) {
        List<FundEastmoneyJjjz> list = fundEastmoneyJjjzMapper.selectCallbackByCode(code);
        return list.get(0).getCallback();
    }

    @Override
    public List<String> selectAllCode() {
        List<FundHistoryNav> fundHistoryNavs = fundHistoryNavMapper.selectAllCode();
        List<String> list = new ArrayList<>();
        for (FundHistoryNav fundHistoryNav : fundHistoryNavs) {
            list.add(fundHistoryNav.getCode());
        }
        return list;
    }

    @Override
    public void updateHistoryNavByConditions(String code, Date date) throws ParseException, IOException {
        List<FundHistoryNav> navList = fundHistoryNavMapper.selectLastFundHistoryNavDateAndNav();
        String callback = selectCallbackByCode(code);
        if (navList.isEmpty()) {
            String navStr = retryUpdateHistoryNav(code, date);
            if (navStr == null || navStr.equals("")) {
                throw new FundTransactionException(999,
                    "failed to update history nav, because nav is null or '' after retryUpdateHistoryNav(String code, Date navDate)");
            }
            navList = fundHistoryNavMapper.selectLastFundHistoryNavDateAndNav();
        }
        FundHistoryNav historyNav = navList.get(0);
        Date lastNavDate = historyNav.getNavDate();
        if (date.compareTo(lastNavDate) >= 0) {
            insertFundHistoryNav(code, DateUtil.dateToStr(lastNavDate), DateUtil.dateToStr(date), callback);
        } else {
            throw new FundTransactionException(999, "updatenavDate should be larger than or equals to last navDate");
        }
    }

    /**
     * insert `fund_history_nav` with:
     * <br/>
     * 1.code, 2.nav_date, 3.nav, 4.callback
     * <p/>
     * 尝试更新 nav, case0: 更新前7天, case1: 更新前14天, case2: 更新前30天, case3: 从 2023-08-01 开始更新
     *
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
            Date date = switch (i) {
                case 0 -> TransactionDayUtil.getLastNTransactionDate(navDate, 7);
                case 1 -> TransactionDayUtil.getLastNTransactionDate(navDate, 14);
                case 2 -> TransactionDayUtil.getLastNTransactionDate(navDate, 30);
                default -> DateUtil.strToDate("2023-08-01");
            };
            insertFundHistoryNav(code, DateUtil.dateToStr(date), DateUtil.dateToStr(navDate), callback);
            navStr = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate).get(0).getNav();
        }
        return navStr;
    }
}
