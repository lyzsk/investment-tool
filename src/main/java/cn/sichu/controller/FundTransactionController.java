package cn.sichu.controller;

import cn.sichu.annotation.LogAnnotation;
import cn.sichu.common.Resp;
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
    @LogAnnotation(module = "FundTransactionController", operation = "purchaseFund")
    public Resp<String> purchaseFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("amount") String amount, @RequestParam("tradingPlatform") String tradingPlatform) throws ParseException {
        return fundTransactionService.purchaseFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(amount), tradingPlatform);
    }

    @PostMapping("/redemption")
    @LogAnnotation(module = "FundTransactionController", operation = "redemptionFund")
    public Resp<String> redemptionFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("share") String share, @RequestParam("tradingPlatform") String tradingPlatform) throws ParseException {
        return fundTransactionService.redeemFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(share), tradingPlatform);
    }

    @PostMapping("/dividend")
    public Resp<String> dividendFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("dividendAmountPerShare") String dividendAmountPerShare, @RequestParam("tradingPlatform") String tradingPlatform)
        throws ParseException {
        return fundTransactionService.dividendFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(dividendAmountPerShare),
            tradingPlatform);
    }

    @Scheduled(cron = "30 0 0 * * *")
    @PostMapping("/updateStatus")
    @LogAnnotation(module = "FundTransactionController", operation = "updateStatusForTransactionInTransit")
    public Resp<String> updateStatusForTransactionInTransit() {
        Date date = new Date();
        Resp<String> resp1 = fundTransactionService.updateStatusForTransactionInTransit(date);
        Resp<String> resp2 = fundTransactionService.updateHeldDaysAndUpdateDateForFundPosition(date);
        if (resp1.getMsg().equals("success") && resp2.getMsg().equals("success")) {
            return Resp.success("updateStatusForTransactionInTransit and updateHeldDaysAndUpdateDateForFundPosition success");
        } else {
            return Resp.error(resp1.getMsg() + "\n" + resp2.getMsg());
        }
    }

    @Scheduled(cron = "0 0/15 20-23 * * *")
    @PostMapping("/updateNav")
    @LogAnnotation(module = "FundTransactionController", operation = "updateNavAndShare")
    public Resp<String> updateNavAndShare() throws ParseException, IOException {
        Date date = new Date();
        List<String> codeList = fundHistoryNavService.selectAllCode();
        for (String code : codeList) {
            fundHistoryNavService.updateHistoryNavByConditions(code, date);
        }
        return fundTransactionService.dailyUpdateFundTransactionAndFundPosition();
    }

}
