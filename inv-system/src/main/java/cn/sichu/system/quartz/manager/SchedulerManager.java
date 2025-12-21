package cn.sichu.system.quartz.manager;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.handler.JobHandlerInvoker;
import enums.MisfirePolicy;
import lombok.RequiredArgsConstructor;
import org.quartz.*;
import org.springframework.stereotype.Service;
import result.ResultCode;
import utils.CronUtils;

/**
 * 封装 Cron校验, MisfirePolicy 策略, Quartz操作等功能
 * <p/>
 * SysJob(DB table) -> SchedulerManager(add/update/delete) -> QuartzScheduler(JDBCJobStore) ->
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
        JobDetail jobDetail =
            JobBuilder.newJob(JobHandlerInvoker.class).withIdentity(sysJob.getJobHandlerName())
                .usingJobData("JOB_ID", sysJob.getId())
                .usingJobData("JOB_HANDLER_NAME", sysJob.getJobHandlerName())
                .usingJobData("JOB_HANDLER_PARAM", sysJob.getJobHandlerParam()).storeDurably()
                .build();

        CronScheduleBuilder scheduleBuilder =
            CronScheduleBuilder.cronSchedule(sysJob.getCronExpression());
        applyMisfirePolicy(scheduleBuilder, sysJob.getMisfirePolicy());

        Trigger trigger = TriggerBuilder.newTrigger().withIdentity(sysJob.getJobHandlerName())
            .withSchedule(scheduleBuilder).usingJobData("RETRY_COUNT", sysJob.getRetryCount())
            .usingJobData("RETRY_INTERVAL", sysJob.getRetryInterval()).build();
        scheduler.scheduleJob(jobDetail, trigger);
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
        JobKey jobKey = JobKey.jobKey(sysJob.getJobHandlerName());
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
        JobKey jobKey = JobKey.jobKey(sysJob.getJobHandlerName());
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
        JobKey jobKey = JobKey.jobKey(sysJob.getJobHandlerName());
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
        JobKey jobKey = JobKey.jobKey(sysJob.getJobHandlerName());
        if (scheduler.checkExists(jobKey)) {
            JobDataMap dataMap = new JobDataMap();
            dataMap.put("JOB_ID", sysJob.getId());
            dataMap.put("JOB_HANDLER_NAME", sysJob.getJobHandlerName());
            dataMap.put("JOB_HANDLER_PARAM", sysJob.getJobHandlerParam());
            scheduler.triggerJob(jobKey, dataMap);
        } else {
            throw new SchedulerException(
                "任务 [" + sysJob.getJobHandlerName() + "] 不存在，无法触发");
        }
    }

    /**
     * @param sysJob sysJob
     * @return boolean 检查任务是否存在
     * @author sichu huang
     * @since 2025/12/21 12:00:18
     */
    public boolean exists(SysJob sysJob) throws SchedulerException {
        return scheduler.checkExists(JobKey.jobKey(sysJob.getJobHandlerName()));
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
            case EXECUTE_IMMEDIATELY:
                builder.withMisfireHandlingInstructionIgnoreMisfires();
                break;
            case EXECUTE_ONCE:
                builder.withMisfireHandlingInstructionFireAndProceed();
                break;
            case ABADON_EXECUTION:
            default:
                builder.withMisfireHandlingInstructionDoNothing();
                break;
        }
    }
}
