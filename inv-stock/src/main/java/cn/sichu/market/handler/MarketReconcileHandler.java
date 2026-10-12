package cn.sichu.market.handler;

import cn.sichu.market.service.IMarketPipelineService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Component("marketReconcileHandler")
@RequiredArgsConstructor
public class MarketReconcileHandler implements JobHandler {
    private final IMarketPipelineService marketPipelineService;

    /**
     * 行情库对账+补采(第 6 段): 收盘任务之后跑一次兜底(15:35 任务失败/源未更新时自动重来), 应用启动后也自动跑一次(MarketStartupRunner)
     *
     * @author sichu huang
     * @param params 不用
     * @since 2026/10/12
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        return marketPipelineService.reconcile();
    }
}
