package cn.sichu.system.quartz.manager;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.mapper.SysJobMapper;
import cn.sichu.system.quartz.runner.SysJobRunner;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import enums.QuartzStatus;
import enums.TableLogic;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.scheduling.support.CronTrigger;
import org.springframework.stereotype.Component;
import utils.StringUtils;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;

/**
 * @author sichu huang
 * @since 2025/12/07 15:24
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class ScheduledTaskManager {
    private final ThreadPoolTaskScheduler taskScheduler;
    private final SysJobRunner sysJobRunner;
    private final SysJobMapper sysJobMapper;

    /* 任务ID -> ScheduledFuture 映射 */
    private final Map<Long, ScheduledFuture<?>> scheduledTasks = new ConcurrentHashMap<>();

    /**
     * 添加定时任务
     *
     * @param job SysJob
     * @author sichu huang
     * @since 2025/12/07 16:23:04
     */
    public void addJob(SysJob job) {
        if (job == null || StringUtils.isEmpty(job.getCronExpression())) {
            return;
        }
        removeJob(job.getId());
        Runnable task = () -> sysJobRunner.run(job);
        CronTrigger trigger = new CronTrigger(job.getCronExpression());
        ScheduledFuture<?> future = taskScheduler.schedule(task, trigger);
        scheduledTasks.put(job.getId(), future);
        log.info("已添加定时任务: {} (cron: {})", job.getJobName(), job.getCronExpression());
    }

    /**
     * 移除定时任务
     *
     * @param id id
     * @author sichu huang
     * @since 2025/12/07 16:23:26
     */
    public void removeJob(Long id) {
        ScheduledFuture<?> future = scheduledTasks.remove(id);
        if (future != null) {
            future.cancel(true); // 中断正在执行的任务
            log.info("已取消定时任务 ID: {}", id);
        }
    }

    /**
     * 立即执行一次
     *
     * @param id id
     * @author sichu huang
     * @since 2025/12/07 16:24:01
     */
    public void runOnce(Long id) {
        SysJob job = sysJobMapper.selectById(id);
        if (job != null && job.getIsDeleted() != TableLogic.DELETED.getCode()) {
            CompletableFuture.runAsync(() -> sysJobRunner.run(job));
        }
    }

    /**
     * 启动时加载所有运行中的任务
     *
     * @author sichu huang
     * @since 2025/12/07 16:25:16
     */
    @PostConstruct
    public void init() {
        LambdaQueryWrapper<SysJob> query = new LambdaQueryWrapper<>();
        query.eq(SysJob::getStatus, QuartzStatus.RUNNING.getCode())
            .eq(SysJob::getIsDeleted, TableLogic.NOT_DELETED.getCode());
        List<SysJob> jobs = sysJobMapper.selectList(query);
        for (SysJob job : jobs) {
            addJob(job);
        }
        log.info("加载并调度了 {} 个定时任务", jobs.size());
    }
}
