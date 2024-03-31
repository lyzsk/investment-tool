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
@RequestMapping("/transaction")
public class FundTransactionController {
    @Autowired
    IFundTransactionService fundTransactionService;
    @Autowired
    IFundHistoryNavService fundHistoryNavService;

    @PostMapping("/purchase")
    public void purchaseFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("amount") String amount, @RequestParam("tradingPlatform") String tradingPlatform) throws ParseException, IOException {
        fundTransactionService.insertFundPurchaseTransactionByConditions(code, DateUtil.strToDate(applicationDate), new BigDecimal(amount),
            tradingPlatform);
    }

    @PostMapping("/redemption")
    public void RedemptionFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("share") String share, @RequestParam("tradingPlatform") String tradingPlatform) throws ParseException, IOException {
        fundTransactionService.insertFundRedemptionTransactionByConditions(code, DateUtil.strToDate(applicationDate), new BigDecimal(share),
            tradingPlatform);
    }

    @Scheduled(cron = "0 30 9 * * *")
    @PostMapping("/update-status")
    public void updateStatusForTransactionInTransit() throws ParseException, IOException {
        Date date = new Date();
        fundTransactionService.updateTotalAmountAndHeldDaysAndUpdateDateForFundPosition(date);
        fundTransactionService.updateStatusForTransactionInTransit(date);
    }

    @Scheduled(cron = "0 0 20-23 * * *")
    @PostMapping("/update-fund-transaction")
    public void updateNavAndShare() throws ParseException, IOException {
        Date date = new Date();
        List<String> codes = fundHistoryNavService.selectAllCode();
        for (String code : codes) {
            fundHistoryNavService.updateHistoryNavByConditions(code, date);
        }
        fundTransactionService.updateNavAndShareForFundPurchaseTransaction();
        fundTransactionService.updateNavAndFeeAndAmountForFundRedemptionTransaction();
    }

}
