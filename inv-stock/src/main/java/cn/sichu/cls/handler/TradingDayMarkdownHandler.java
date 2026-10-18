package cn.sichu.cls.handler;

import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.time.LocalDate;

/**
 * @author sichu huang
 * @since 2026/01/14 14:18
 */
@Component("tradingDayMarkdownHandler")
@RequiredArgsConstructor
public class TradingDayMarkdownHandler implements JobHandler {
    private final IClsTelegraphService clsTelegraphService;

    @Override
    public String execute(String params) throws Exception {
        /* 在 00:00 创建下一个交易日的 Markdown 文件 */
        boolean success = clsTelegraphService.generateMarkdown(LocalDate.now());
        return "Markdown 初始化: " + (success ? "成功" : "失败");
    }
}
