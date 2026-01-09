package cn.sichu.cls.handler;

import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * @author sichu huang
 * @since 2026/01/03 17:06
 */
@Component("clsTelegraphCrawlerHandler")
@RequiredArgsConstructor
public class ClsTelegraphCrawlerHandler implements JobHandler {
    private final IClsTelegraphService clsTelegraphService;

    @Override
    public String execute(String params) {
        int sp = clsTelegraphService.fetchAndSaveShouPingTelegraphs();
        int zt = clsTelegraphService.fetchAndSaveZhangTingTelegraphs();
        return "CLS 电报收评爬取完成, 新增" + sp + "条" + "CLS 电报涨停分析爬取完成, 新增" + zt
            + "条";
    }
}
