package cn.sichu.controller;

import cn.sichu.annotation.LogAnnotation;
import cn.sichu.common.Resp;
import cn.sichu.service.IGoldTransactionService;
import org.apache.poi.ss.formula.functions.T;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * @author sichu huang
 * @date 2024/06/24
 **/
@RestController
@RequestMapping("/goldTransaction")
public class GoldTransactionController {
    @Autowired
    IGoldTransactionService goldTransactionService;

    @PostMapping("/purchase")
    @LogAnnotation(module = "GoldTransactionController", operation = "purchaseGold")
    public Resp<T> purchaseGold(@RequestParam("pricePerGram") String pricePerGram, @RequestParam("grams") String grams,
        @RequestParam("transactionTime") String transactionTime, @RequestParam("tradingPlatform") String tradingPlatform) {
        try {
            goldTransactionService.purchaseGold(pricePerGram, grams, transactionTime, tradingPlatform);
            return Resp.success("purchase gold success!");
        } catch (Exception e) {
            return Resp.error(e.getMessage());
        }
    }

    @PostMapping("/redeem")
    @LogAnnotation(module = "GoldTransactionController", operation = "redeemGold")
    public Resp<T> redeemGold(@RequestParam("pricePerGram") String pricePerGram, @RequestParam("grams") String grams,
        @RequestParam("transactionTime") String transactionTime, @RequestParam("tradingPlatform") String tradingPlatform) {
        try {
            goldTransactionService.redeemGold(pricePerGram, grams, transactionTime, tradingPlatform);
            return Resp.success("redeem gold success!");
        } catch (Exception e) {
            return Resp.error(e.getMessage());
        }
    }
}
