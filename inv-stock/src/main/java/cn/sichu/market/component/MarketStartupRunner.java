package cn.sichu.market.component;

import cn.sichu.market.service.IMarketPipelineService;
import cn.sichu.system.config.ProjectConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Slf4j
@Component
@RequiredArgsConstructor
public class MarketStartupRunner implements ApplicationRunner {
    private final ProjectConfig projectConfig;
    private final IMarketPipelineService marketPipelineService;

    /**
     * Quartz 是内存存储, 停机/断电期间到点的收盘采集重启后不会补跑 → 启动后延迟 N 分钟在后台对账一次, 缺哪天补哪天
     * 不阻塞启动; 延迟=0 关闭
     *
     * @author sichu huang
     * @param args args
     * @since 2026/10/12
     **/
    @Override
    public void run(ApplicationArguments args) {
        int delayMin = projectConfig.getMarket().getReconcileOnStartupDelayMin();
        if (delayMin <= 0) {
            return;
        }
        CompletableFuture.runAsync(() -> {
            try {
                log.info("启动对账: {}", marketPipelineService.reconcile());
            } catch (Exception e) {
                log.error("启动对账失败", e);
            }
        }, CompletableFuture.delayedExecutor(delayMin, TimeUnit.MINUTES));
    }
}
