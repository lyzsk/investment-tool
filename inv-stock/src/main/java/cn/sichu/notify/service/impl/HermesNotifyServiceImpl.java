package cn.sichu.notify.service.impl;

import cn.sichu.notify.service.INotifyService;
import cn.sichu.system.config.ProjectConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import utils.ProcessUtils;
import utils.StringUtils;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Slf4j
@Service
@RequiredArgsConstructor
public class HermesNotifyServiceImpl implements INotifyService {
    private static final int MAX_TRY = 3;
    private final ProjectConfig projectConfig;

    @Override
    public void sendAsync(String message) {
        String exe = projectConfig.getNotify().getHermesExe();
        if (StringUtils.isEmpty(exe) || !Files.exists(Paths.get(exe))) {
            log.warn("未配置 hermes(project.notify.hermes-exe), 消息只记日志: {}", message);
            return;
        }
        CompletableFuture.runAsync(() -> {
            for (int i = 1; i <= MAX_TRY; i++) {
                try {
                    /* 与 scripts/dfcf/paper/daily_digest.mjs 同一调用方式 */
                    ProcessUtils.runChecked(
                        new ProcessBuilder(exe, "send", "--to", projectConfig.getNotify().getHermesTo(), message), 2,
                        "hermes send");
                    return;
                } catch (Exception e) {
                    log.warn("hermes 推送失败 {}/{}: {}", i, MAX_TRY, e.getMessage());
                    if (i < MAX_TRY) {
                        try {
                            TimeUnit.SECONDS.sleep(60);
                        } catch (InterruptedException ie) {
                            Thread.currentThread().interrupt();
                            return;
                        }
                    }
                }
            }
            log.error("hermes 推送放弃, 消息: {}", message);
        });
    }
}
