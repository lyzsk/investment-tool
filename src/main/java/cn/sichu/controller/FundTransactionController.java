package cn.sichu.controller;

import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.service.IFundTransactionService;
import cn.sichu.utils.DateUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.math.BigDecimal;
import java.text.ParseException;
import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/18
 **/
@RestController
@RequestMapping("/fundTransaction")
public class FundTransactionController {
    @Autowired
    IFundTransactionService fundTransactionService;
    @Autowired
    IFundHistoryNavService fundHistoryNavService;

    @PostMapping("/purchase")
    public void purchaseFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("amount") String amount, @RequestParam("tradingPlatform") String tradingPlatform) throws ParseException, IOException {
        fundTransactionService.purchaseFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(amount), tradingPlatform);
    }

    @PostMapping("/redemption")
    public void redemptionFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("share") String share, @RequestParam("tradingPlatform") String tradingPlatform) throws ParseException, IOException {
        fundTransactionService.redeemFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(share), tradingPlatform);
    }

    @PostMapping("/dividend")
    public void dividendFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("dividendAmountPerShare") String dividendAmountPerShare, @RequestParam("tradingPlatform") String tradingPlatform)
        throws ParseException {
        fundTransactionService.dividendFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(dividendAmountPerShare), tradingPlatform);
    }

    @Scheduled(cron = "30 0 0 * * *")
    @PostMapping("/updateStatus")
    public void updateStatusForTransactionInTransit() throws ParseException, IOException {
        Date date = new Date();
        fundTransactionService.updateStatusForTransactionInTransit(date);
        fundTransactionService.updateHeldDaysAndUpdateDateForFundPosition(date);
    }

    @Scheduled(cron = "0 0/15 20-23 * * *")
    @PostMapping("/updateNav")
    public void updateNavAndShare() throws ParseException, IOException {
        Date date = new Date();
        List<String> codeList = fundHistoryNavService.selectAllCode();
        for (String code : codeList) {
            fundHistoryNavService.updateHistoryNavByConditions(code, date);
        }
        fundTransactionService.dailyUpdateFundTransactionAndFundPosition();
    }

}
