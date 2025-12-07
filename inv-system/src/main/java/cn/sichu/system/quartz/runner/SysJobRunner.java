package cn.sichu.system.quartz.runner;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.entity.SysJobLog;
import cn.sichu.system.quartz.service.ISysJobLogService;
import enums.BusinessStatus;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.ApplicationContext;
import org.springframework.stereotype.Component;
import utils.ExceptionUtils;
import utils.StringUtils;

import java.lang.reflect.Method;
import java.time.LocalDateTime;
import java.util.concurrent.CompletableFuture;

/**
 * @author sichu huang
 * @since 2025/12/07 15:24
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class SysJobRunner {

    private final ApplicationContext applicationContext;
    private final ISysJobLogService sysJobLogService;

    public void run(SysJob job) {
        SysJobLog jobLog = new SysJobLog();
        jobLog.setJobName(job.getJobName());
        jobLog.setJobGroup(job.getJobGroup());
        jobLog.setInvokeTarget(job.getInvokeTarget());
        jobLog.setCreateBy(job.getCreateBy());
        jobLog.setCreateTime(LocalDateTime.now());
        long startTime = System.currentTimeMillis();
        try {
            /* invokeTarget 格式为 'beanName.methodName(params)'，Spring 默认 Bean 名称为 首字母小写 */
            String beanName = getBeanName(job.getInvokeTarget());
            String methodName = getMethodName(job.getInvokeTarget());
            String methodParams = getMethodParams(job.getInvokeTarget());
            Object bean = applicationContext.getBean(beanName);
            Method method = getMethod(bean.getClass(), methodName, methodParams);
            Object[] args = buildMethodParams(method, methodParams);
            method.invoke(bean, args);
            jobLog.setStatus(BusinessStatus.SUCCESS.getCode());
            jobLog.setJobMessage(
                "定时任务执行成功, 耗时 " + (System.currentTimeMillis() - startTime) + "ms");
            log.info("定时任务 [{}] 执行成功", job.getJobName());
        } catch (Exception e) {
            String errorMsg = "执行失败: " + e.getMessage();
            jobLog.setStatus(BusinessStatus.FAILED.getCode());
            jobLog.setExceptionMessage(ExceptionUtils.stacktraceToString(e, 2000));
            jobLog.setJobMessage(errorMsg);
            log.error("定时任务 [{}] 执行异常", job.getJobName(), e);
        } finally {
            /* 异步保存日志（避免阻塞调度线程）*/
            CompletableFuture.runAsync(() -> sysJobLogService.save(jobLog));
        }
    }

    private String getBeanName(String invokeTarget) {
        if (invokeTarget.contains(StringUtils.DOT)) {
            return invokeTarget.substring(0, invokeTarget.indexOf(StringUtils.DOT));
        }
        throw new IllegalArgumentException("调用目标格式错误，应为 'beanName.methodName(...)'");
    }

    private String getMethodName(String invokeTarget) {
        String methodStr = invokeTarget.substring(invokeTarget.indexOf(StringUtils.DOT) + 1);
        if (methodStr.contains(StringUtils.LEFT_BRACKET)) {
            return methodStr.substring(0, methodStr.indexOf(StringUtils.LEFT_BRACKET));
        }
        return methodStr;
    }

    private String getMethodParams(String invokeTarget) {
        if (invokeTarget.contains(StringUtils.LEFT_BRACKET) && invokeTarget.contains(
            StringUtils.RIGHT_BRACKET)) {
            return invokeTarget.substring(invokeTarget.indexOf(StringUtils.LEFT_BRACKET) + 1,
                invokeTarget.lastIndexOf(StringUtils.RIGHT_BRACKET));
        }
        return StringUtils.EMPTY;
    }

    private Method getMethod(Class<?> clazz, String methodName, String params) {
        Class<?>[] paramTypes;
        /* 简化参数, 仅支持无参或单个 String 参数 */
        if (StringUtils.isNotEmpty(params)) {
            paramTypes = new Class[] {String.class};
        } else {
            paramTypes = new Class[0];
        }
        try {
            return clazz.getMethod(methodName, paramTypes);
        } catch (NoSuchMethodException e) {
            throw new RuntimeException("未找到方法: " + methodName + " in " + clazz.getName(), e);
        }
    }

    private Object[] buildMethodParams(Method method, String params) {
        if (method.getParameterCount() == 0) {
            return new Object[0];
        } else if (method.getParameterCount() == 1
            && method.getParameterTypes()[0] == String.class) {
            return new Object[] {params};
        } else {
            throw new UnsupportedOperationException(
                "暂不支持复杂参数类型，仅支持无参或单个 String 参数");
        }
    }
}
