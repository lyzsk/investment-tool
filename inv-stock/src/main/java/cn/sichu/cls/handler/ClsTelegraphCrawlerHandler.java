package cn.sichu.cls.handler;

import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.system.quartz.handler.JobHandler;
import org.springframework.stereotype.Component;

/**
 * @author sichu huang
 * @since 2026/01/03 17:06
 */
@Component("clsTelegraphCrawlerHandler")
public class ClsTelegraphCrawlerHandler implements JobHandler {
    private final IClsTelegraphService clsTelegraphService;

    public ClsTelegraphCrawlerHandler(IClsTelegraphService clsTelegraphService) {
        this.clsTelegraphService = clsTelegraphService;
    }

    @Override
    public String execute(String params) throws Exception {
        clsTelegraphService.fetchAndSaveLatestTelegraphs();
        return "CLS 电报爬取完成";
    }
}
