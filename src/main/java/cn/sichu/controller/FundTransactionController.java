package cn.sichu.controller;

import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.service.IFundPositionService;
import cn.sichu.service.IFundTransactionService;
import cn.sichu.utils.DateUtil;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.math.BigDecimal;
import java.text.ParseException;
import java.util.Date;

/**
 * @author sichu huang
 * @date 2024/03/18
 **/
@RestController
@RequestMapping("/transaction")
public class FundTransactionController {
    @Autowired
    IFundTransactionService fundTransactionService;
    @Autowired
    IFundHistoryNavService fundHistoryNavService;
    @Autowired
    IFundPositionService fundPositionService;

    @PostMapping("/purchase")
    public void purchaseFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("amount") String amount, @RequestParam("tradingPlatform") String tradingPlatform)
        throws ParseException, IOException {
        Date date = DateUtil.strToDate(applicationDate);
        String callback = fundHistoryNavService.selectCallbackByCode(code);
        String startDate = DateUtil.dateToStr(TransactionDayUtil.getLastNTransactionDate(date, 3));
        fundHistoryNavService.insertFundHistoryNavInformation(code, startDate, applicationDate, callback);
        fundTransactionService.insertFundPurchaseTransactionByConditions(code, date, new BigDecimal(amount),
            tradingPlatform);
        fundTransactionService.updateNavAndShareForFundPurchaseTransaction(date);
        fundTransactionService.updateStatusForFundPurchaseTransaction(date);
        fundTransactionService.updateStatusForFundTransaction(date);
    }
}
