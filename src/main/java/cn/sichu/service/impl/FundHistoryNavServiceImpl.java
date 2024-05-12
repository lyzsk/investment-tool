package cn.sichu.service.impl;

import cn.sichu.entity.FundEastmoneyJjjz;
import cn.sichu.entity.FundHistoryNav;
import cn.sichu.entity.FundTransaction;
import cn.sichu.enums.AppExceptionCodeMsg;
import cn.sichu.exception.FundTransactionException;
import cn.sichu.mapper.FundEastmoneyJjjzMapper;
import cn.sichu.mapper.FundHistoryNavMapper;
import cn.sichu.mapper.FundTransactionMapper;
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
    @Autowired
    FundTransactionMapper fundTransactionMapper;

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
        /* isEmpty的情况: 1.历史净值已更新但未入表, 需要根据callback查询和插入; 2.历史净值未更新, 返回"";  */
        Date currentDate = DateUtil.formatDate(new Date());
        String callback = selectCallbackByCode(code);
        if (navDate.before(currentDate)) {
            insertFundHistoryNav(code, DateUtil.dateToStr(navDate), DateUtil.dateToStr(navDate), callback);
            fundHistoryNavList = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
            return fundHistoryNavList.get(0).getNav();
        } else if (navDate.equals(currentDate)) {
            if (CrawlUtil.getDailyNavMapBetweenDates(code, DateUtil.dateToStr(navDate), DateUtil.dateToStr(navDate), callback).isEmpty()) {
                return "";
            }
            insertFundHistoryNav(code, DateUtil.dateToStr(navDate), DateUtil.dateToStr(navDate), callback);
            fundHistoryNavList = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, navDate);
            return fundHistoryNavList.get(0).getNav();
        } else if (navDate.after(currentDate)) {
            throw new FundTransactionException(999, "navDate should be earlier than or equals to currentDate");
        }
        return "";
    }

    @Override
    public String selectCallbackByCode(String code) {
        List<FundEastmoneyJjjz> list = fundEastmoneyJjjzMapper.selectCallbackByCode(code);
        return list.get(0).getCallback();
    }

    @Override
    public List<String> selectAllCode() {
        List<FundTransaction> list = fundTransactionMapper.selectAllCode();
        List<String> codeList = new ArrayList<>();
        for (FundTransaction transaction : list) {
            codeList.add(transaction.getCode());
        }
        return codeList;
    }

    @Override
    public List<String> selectAllHeldCode() {
        List<FundTransaction> list = fundTransactionMapper.selectAllHeldCode();
        List<String> codeList = new ArrayList<>();
        for (FundTransaction transaction : list) {
            codeList.add(transaction.getCode());
        }
        return codeList;
    }

    @Override
    public String selectLastHistoryNav(String code) {
        return fundHistoryNavMapper.selectLastHistoryNav(code).get(0).getNav();
    }

    @Override
    public void updateHistoryNavByConditions(String code, Date date) throws ParseException, IOException {
        Date currentDate = DateUtil.formatDate(date);
        List<FundHistoryNav> navList = fundHistoryNavMapper.selectFundHistoryNavByConditions(code, currentDate);
        if (!navList.isEmpty()) {
            return;
        }
        String callback = selectCallbackByCode(code);
        List<FundHistoryNav> lastHistoryNav = fundHistoryNavMapper.selectLastHistoryNav(code);
        if (lastHistoryNav.isEmpty()) {
            throw new FundTransactionException(AppExceptionCodeMsg.FUND_TRANSACTION_EXCEPTION.getCode(),
                "can't find last history nav and date, please manual init!");
        }
        Date lastDate = lastHistoryNav.get(0).getNavDate();
        if (CrawlUtil.getDailyNavMapBetweenDates(code, DateUtil.dateToStr(lastDate), DateUtil.dateToStr(currentDate), callback).isEmpty()) {
            return;
        }
        insertFundHistoryNav(code, DateUtil.dateToStr(lastDate), DateUtil.dateToStr(currentDate), callback);
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
