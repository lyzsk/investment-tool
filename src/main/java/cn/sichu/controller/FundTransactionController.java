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

import java.math.BigDecimal;
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
        @RequestParam("amount") String amount, @RequestParam("tradingPlatform") String tradingPlatform) {
        try {
            fundTransactionService.purchaseFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(amount), tradingPlatform);
            return Resp.success("purchase fund success!");
        } catch (Exception e) {
            return Resp.error(e.getMessage());
        }
    }

    @PostMapping("/redemption")
    @LogAnnotation(module = "FundTransactionController", operation = "redemptionFund")
    public Resp<String> redemptionFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("share") String share, @RequestParam("tradingPlatform") String tradingPlatform) {
        try {
            fundTransactionService.redeemFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(share), tradingPlatform);
            return Resp.success("redeem fund success!");
        } catch (Exception e) {
            return Resp.error(e.getMessage());
        }
    }

    @PostMapping("/dividend")
    public Resp<String> dividendFund(@RequestParam("code") String code, @RequestParam("applicationDate") String applicationDate,
        @RequestParam("dividendAmountPerShare") String dividendAmountPerShare, @RequestParam("tradingPlatform") String tradingPlatform) {
        try {
            fundTransactionService.dividendFund(code, DateUtil.strToDate(applicationDate), new BigDecimal(dividendAmountPerShare),
                tradingPlatform);
            return Resp.success("dividend fund success!");
        } catch (Exception e) {
            return Resp.error(e.getMessage());
        }
    }

    @Scheduled(cron = "30 0 0 * * *")
    @PostMapping("/updateStatus")
    @LogAnnotation(module = "FundTransactionController", operation = "updateStatusForTransactionInTransit")
    public Resp<String> updateStatusForTransactionInTransit() {
        try {
            Date date = new Date();
            fundTransactionService.updateStatusForTransactionInTransit(date);
            fundTransactionService.updateHeldDaysAndUpdateDateForFundPosition(date);
            return Resp.success("update status and held days for transaction in transit success!");
        } catch (Exception e) {
            return Resp.error(e.getMessage());
        }
    }

    @Scheduled(cron = "0 0/15 20-23 * * *")
    @PostMapping("/updateNav")
    @LogAnnotation(module = "FundTransactionController", operation = "updateNavAndShare")
    public Resp<String> updateNavAndShare() {
        try {
            Date date = new Date();
            List<String> codeList = fundHistoryNavService.selectAllCode();
            for (String code : codeList) {
                fundHistoryNavService.updateHistoryNavByConditions(code, date);
            }
            fundTransactionService.dailyUpdateFundTransactionAndFundPosition();
            return Resp.success("update nav and share and fund transaction and fund position success!");
        } catch (Exception e) {
            return Resp.error(e.getMessage());
        }
    }
}
