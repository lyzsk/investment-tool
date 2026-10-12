package cn.sichu.bilibili.handler;

import cn.sichu.bilibili.service.IBilibiliReconcileService;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Component("bilibiliReconcileHandler")
@RequiredArgsConstructor
public class BilibiliReconcileHandler implements JobHandler {
    private final IBilibiliReconcileService bilibiliReconcileService;

    /**
     * UP 视频管线对账(results / md / distill 账本 / bilibili_video 四方核对 + DB 同步), 见 IBilibiliReconcileService.reconcile
     *
     * @author sichu huang
     * @param params 不用
     * @since 2026/10/12
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        return bilibiliReconcileService.reconcile();
    }
}
