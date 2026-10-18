package cn.sichu.system.quartz.component;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.manager.SchedulerManager;
import cn.sichu.system.quartz.service.ISysJobService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import enums.QuartzStatus;
import enums.TableLogic;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * @author sichu huang
 * @since 2026/01/05 16:11
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class JobInitializationRunner implements CommandLineRunner {
    private final ISysJobService sysJobService;
    private final SchedulerManager schedulerManager;

    @Override
    public void run(String... args) {
        log.info("开始初始化定时任务...");

        List<SysJob> jobs = sysJobService.list(
            new LambdaQueryWrapper<SysJob>().eq(SysJob::getStatus, QuartzStatus.RUNNING.getCode())
                .eq(SysJob::getIsDeleted, TableLogic.NOT_DELETED.getCode()));

        for (SysJob job : jobs) {
            try {
                schedulerManager.addJob(job);
                log.info("✅ 成功注册任务: name={}, group={}", job.getJobHandlerName(),
                    job.getJobGroup());
            } catch (Exception e) {
                log.error("❌ 注册任务失败: name={}, group={}, error={}", job.getJobHandlerName(),
                    job.getJobGroup(), e.getMessage(), e);
            }
        }

        log.info("定时任务初始化完成，共注册 {} 个任务", jobs.size());
    }
}
