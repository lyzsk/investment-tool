package cn.sichu.system.quartz.handler;

import cn.sichu.system.quartz.entity.SysJobLog;
import cn.sichu.system.quartz.service.ISysJobLogService;
import enums.BusinessStatus;
import lombok.extern.slf4j.Slf4j;
import org.quartz.DisallowConcurrentExecution;
import org.quartz.JobDataMap;
import org.quartz.JobExecutionContext;
import org.quartz.JobExecutionException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.scheduling.quartz.QuartzJobBean;
import org.springframework.stereotype.Component;
import utils.ExceptionUtils;

import java.util.concurrent.CompletableFuture;

/**
 * Quartz Job 入口
 * <p>
 * SysJob(DB table) -> SchedulerManager(add/update/delete) -> JobInitializationRunner(JDBCJobStore) ->
 * JobHandlerInvoker(QuartzJobBean) -> BusinessHandler(e.g. )
 *
 * @author sichu huang
 * @since 2025/12/21 01:06
 */
@Component
@DisallowConcurrentExecution
@Slf4j
public class JobHandlerInvoker extends QuartzJobBean {
    @Autowired
    private ApplicationContext applicationContext;

    @Override
    protected void executeInternal(JobExecutionContext context) throws JobExecutionException {
        JobDataMap data = context.getMergedJobDataMap();
        Long jobId = data.getLong("JOB_ID");
        String handlerName = data.getString("JOB_HANDLER_NAME");
        String param = data.getString("JOB_HANDLER_PARAM");
        /* 日志记录 */
        SysJobLog sysJobLog = new SysJobLog();
        sysJobLog.setJobName(handlerName);
        sysJobLog.setJobHandlerName(handlerName);
        sysJobLog.setJobHandlerParam(param);
        sysJobLog.setStatus(BusinessStatus.SUCCESS.getCode());

        long start = System.currentTimeMillis();
        try {
            JobHandler handler = applicationContext.getBean(handlerName, JobHandler.class);
            String result = handler.execute(param);
            long executionTime = System.currentTimeMillis() - start;
            sysJobLog.setExecutionTime(executionTime);
            sysJobLog.setJobMessage("执行成功，耗时 " + executionTime + "ms, 执行结果：" + result);
        } catch (Exception e) {
            sysJobLog.setStatus(BusinessStatus.FAILED.getCode());
            sysJobLog.setExceptionMessage(ExceptionUtils.getStacktrace(e, 2000));
            sysJobLog.setJobMessage("执行失败：" + e.getMessage());
            throw new JobExecutionException(e);
        } finally {
            /* 异步保存日志, 防止线程阻塞 */
            CompletableFuture.runAsync(() -> {
                try {
                    ISysJobLogService jobLogService =
                        applicationContext.getBean(ISysJobLogService.class);
                    jobLogService.save(sysJobLog);
                } catch (Exception ex) {
                    log.error("保存定时任务日志失败，jobId: {}, error: {}", sysJobLog.getId(),
                        ex.getMessage(), ex);
                }
            });
        }
    }
}
