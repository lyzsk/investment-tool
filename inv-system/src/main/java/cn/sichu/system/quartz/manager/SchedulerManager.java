package cn.sichu.system.quartz.manager;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.enums.MisfirePolicy;
import cn.sichu.system.quartz.handler.JobHandlerInvoker;
import lombok.RequiredArgsConstructor;
import org.quartz.*;
import org.springframework.stereotype.Service;
import result.ResultCode;
import utils.CronUtils;

/**
 * 封装 Cron校验, MisfirePolicy 策略, Quartz操作等功能
 * <p/>
 * SysJob(DB table) -> SchedulerManager(add/update/delete) -> JobInitializationRunner(JDBCJobStore) ->
 * JobHandlerInvoker(QuartzJobBean) -> BusinessHandler(e.g. )
 *
 * @author sichu huang
 * @since 2025/12/21 11:51
 */
@Service
@RequiredArgsConstructor
public class SchedulerManager {

    private final Scheduler scheduler;

    /**
     * 添加定时任务
     *
     * @param sysJob sysJob
     * @author sichu huang
     * @since 2025/12/21 11:57:50
     */
    public void addJob(SysJob sysJob) throws SchedulerException {
        if (!CronUtils.isValid(sysJob.getCronExpression())) {
            throw new IllegalArgumentException(
                ResultCode.INVALID_CRON_EXPRESSION.getMsg() + ": " + sysJob.getCronExpression());
        }
        /* 10/9 修复: JobKey/TriggerKey 原用 handler bean 名, 同 handler 多任务(13 条 paper 链/3 个 B站发现)
           全部撞 key 静默跳过只剩第一个——改用任务 id 唯一化 */
        String jobKey = jobKeyOf(sysJob);
        String jobGroup = sysJob.getJobGroup();
        TriggerKey triggerKey = TriggerKey.triggerKey("TRG_" + jobKey, jobGroup);
        /* 10/16: 暂停态任务手动触发时会先登记一个无 cron 的 durable job(见 triggerJob), 启用时只补 cron 触发器 */
        if (exists(sysJob)) {
            if (!scheduler.checkExists(triggerKey)) {
                scheduler.scheduleJob(cronTrigger(sysJob, triggerKey).forJob(jobKey, jobGroup).build());
            }
            return;
        }
        JobDetail jobDetail = jobDetailOf(sysJob);

        scheduler.scheduleJob(jobDetail, cronTrigger(sysJob, triggerKey).build());
    }

    /**
     * 任务明细(durable: 没有触发器时也保留, 供暂停态手动触发)
     *
     * @param sysJob sysJob
     * @return org.quartz.JobDetail
     * @author sichu huang
     * @since 2026/10/16
     */
    private JobDetail jobDetailOf(SysJob sysJob) {
        return JobBuilder.newJob(JobHandlerInvoker.class).withIdentity(jobKeyOf(sysJob), sysJob.getJobGroup())
            .usingJobData("JOB_ID", sysJob.getId()).usingJobData("JOB_HANDLER_NAME", sysJob.getJobHandlerName())
            .usingJobData("JOB_HANDLER_PARAM", sysJob.getJobHandlerParam()).storeDurably()
            .build();
    }

    /**
     * cron 触发器
     *
     * @param sysJob     sysJob
     * @param triggerKey triggerKey
     * @return org.quartz.TriggerBuilder<org.quartz.CronTrigger>
     * @author sichu huang
     * @since 2026/10/16
     */
    private TriggerBuilder<CronTrigger> cronTrigger(SysJob sysJob, TriggerKey triggerKey) {
        CronScheduleBuilder scheduleBuilder =
            CronScheduleBuilder.cronSchedule(sysJob.getCronExpression());
        applyMisfirePolicy(scheduleBuilder, sysJob.getMisfirePolicy());
        return TriggerBuilder.newTrigger().withIdentity(triggerKey)
            .withSchedule(scheduleBuilder).usingJobData("RETRY_COUNT", sysJob.getRetryCount())
            .usingJobData("RETRY_INTERVAL", sysJob.getRetryInterval());
    }

    /**
     * 更新定时任务(先删除, 再添加)
     *
     * @param sysJob sysJob
     * @author sichu huang
     * @since 2025/12/21 11:58:17
     */
    public void updateJob(SysJob sysJob) throws SchedulerException {
        deleteJob(sysJob);
        addJob(sysJob);
    }

    /**
     * 删除定时任务
     *
     * @param sysJob sysJob
     * @author sichu huang
     * @since 2025/12/21 11:58:49
     */
    public void deleteJob(SysJob sysJob) throws SchedulerException {
        JobKey jobKey = JobKey.jobKey(jobKeyOf(sysJob), sysJob.getJobGroup());
        if (scheduler.checkExists(jobKey)) {
            scheduler.deleteJob(jobKey);
        }
    }

    /**
     * 暂停定时任务
     *
     * @param sysJob sysJob
     * @author sichu huang
     * @since 2025/12/21 11:59:12
     */
    public void pauseJob(SysJob sysJob) throws SchedulerException {
        JobKey jobKey = JobKey.jobKey(jobKeyOf(sysJob), sysJob.getJobGroup());
        if (scheduler.checkExists(jobKey)) {
            scheduler.pauseJob(jobKey);
        }
    }

    /**
     * 恢复定时任务
     *
     * @param sysJob sysJob
     * @author sichu huang
     * @since 2025/12/21 11:59:52
     */
    public void resumeJob(SysJob sysJob) throws SchedulerException {
        JobKey jobKey = JobKey.jobKey(jobKeyOf(sysJob), sysJob.getJobGroup());
        if (scheduler.checkExists(jobKey)) {
            scheduler.resumeJob(jobKey);
        }
    }

    /**
     * 立即触发一次任务执行
     *
     * @param sysJob sysJob
     * @author sichu huang
     * @since 2025/12/21 12:01:26
     */
    public void triggerJob(SysJob sysJob) throws SchedulerException {
        JobKey jobKey = JobKey.jobKey(jobKeyOf(sysJob), sysJob.getJobGroup());
        if (scheduler.checkExists(jobKey)) {
            JobDataMap dataMap = new JobDataMap();
            dataMap.put("JOB_ID", sysJob.getId());
            dataMap.put("JOB_HANDLER_NAME", sysJob.getJobHandlerName());
            dataMap.put("JOB_HANDLER_PARAM", sysJob.getJobHandlerParam());
            scheduler.triggerJob(jobKey, dataMap);
        } else {
            /* 10/16: 暂停态任务不在调度器里(暂停=deleteJob), 原先直接抛"不存在"——
               改为登记一个无 cron 触发器的 durable job 再触发一次: 只跑这一次, 不会按 cron 自动执行; 启用时 addJob 只补触发器 */
            scheduler.addJob(jobDetailOf(sysJob), true);
            JobDataMap dataMap = new JobDataMap();
            dataMap.put("JOB_ID", sysJob.getId());
            dataMap.put("JOB_HANDLER_NAME", sysJob.getJobHandlerName());
            dataMap.put("JOB_HANDLER_PARAM", sysJob.getJobHandlerParam());
            scheduler.triggerJob(jobKey, dataMap);
        }
    }

    /**
     * @param sysJob sysJob
     * @return boolean 检查任务是否存在
     * @author sichu huang
     * @since 2025/12/21 12:00:18
     */
    public boolean exists(SysJob sysJob) throws SchedulerException {
        return scheduler.checkExists(
            JobKey.jobKey(jobKeyOf(sysJob), sysJob.getJobGroup()));
    }

    /** 任务唯一 key(10/9: handler 名→任务 id, 同 handler 多任务共存) */
    private String jobKeyOf(SysJob sysJob) {
        return "JOB_" + sysJob.getId();
    }

    /**
     * 根据 MisfirePolicy 枚举值设置对应的 Quartz 失火策略
     *
     * @param builder           builder
     * @param misfirePolicyCode misfirePolicyCode
     * @author sichu huang
     * @since 2025/12/21 12:43:09
     */
    private void applyMisfirePolicy(CronScheduleBuilder builder, Integer misfirePolicyCode) {
        if (misfirePolicyCode == null) {
            return;
        }
        MisfirePolicy policy = null;
        for (MisfirePolicy p : MisfirePolicy.values()) {
            if (p.getCode() == misfirePolicyCode) {
                policy = p;
                break;
            }
        }
        if (policy == null) {
            return;
        }
        switch (policy) {
            case EXECUTE_IMMEDIATELY -> builder.withMisfireHandlingInstructionIgnoreMisfires();
            case EXECUTE_ONCE -> builder.withMisfireHandlingInstructionFireAndProceed();
            default -> builder.withMisfireHandlingInstructionDoNothing();
        }
    }
}
