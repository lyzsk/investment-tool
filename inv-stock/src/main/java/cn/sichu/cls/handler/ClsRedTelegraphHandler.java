package cn.sichu.cls.handler;

import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.TradingDayUtils;

import java.time.LocalDate;

/**
 * @author sichu huang
 * @since 2026/01/14 14:15
 */
@Component("clsRedTelegraphHandler")
@RequiredArgsConstructor
public class ClsRedTelegraphHandler implements JobHandler {
    private final IClsTelegraphService clsTelegraphService;

    @Override
    public String execute(String params) throws Exception {
        /* 1. 抓取所有 level="B" 电报 */
        int count = clsTelegraphService.fetchAndSaveAllRedTelegraphs();
        /* 2. 确定目标日期: 如果是节假日/周末 -> 下一交易日 */
        LocalDate today = LocalDate.now();
        LocalDate targetDate =
            TradingDayUtils.isTradingDay(today) ? today : TradingDayUtils.getNextTradingDay(today);
        /* 3. 追加到目标日期的 Markdown */
        boolean success = clsTelegraphService.appendRedTelegraphs(targetDate);
        return String.format("CLS 加红电报抓取完成: 新增 %d 条, 追加到 %s: %s", count, targetDate,
            success ? "成功" : "失败");
    }
}
