package cn.sichu.common;

import cn.sichu.annotation.LogAnnotation;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Pointcut;
import org.aspectj.lang.reflect.MethodSignature;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;

/**
 * @author sichu huang
 * @date 2024/05/02
 **/
@Component
@Aspect
public class LogAspect {
    private static final Logger log = LoggerFactory.getLogger(LogAspect.class);
    private static final ObjectMapper objectMapper = new ObjectMapper();

    @Pointcut("@annotation(cn.sichu.annotation.LogAnnotation)")
    public void point() {

    }

    @Around("point()")
    public Object log(ProceedingJoinPoint joinPoint) throws Throwable {
        long startTime = System.currentTimeMillis();
        Object result = joinPoint.proceed();
        long time = System.currentTimeMillis() - startTime;
        recordLog(joinPoint, time);
        return result;
    }

    private void recordLog(ProceedingJoinPoint joinPoint, long time) {
        MethodSignature signature = (MethodSignature)joinPoint.getSignature();
        Method method = signature.getMethod();
        LogAnnotation logAnnotation = method.getAnnotation(LogAnnotation.class);
        log.info("====================log start====================");
        log.info("module: {}", logAnnotation.module());
        log.info("operation: {}", logAnnotation.operation());
        String className = joinPoint.getTarget().getClass().getName();
        String methodName = signature.getName();
        log.info("request method: {}", className + "." + methodName);
        // Object[] args = joinPoint.getArgs();
        // String params = JSON.toJSONString(args[0]);
        // log.info("params: {}", params);
        log.info("excution time: {} ms", time);
        log.info("====================log end====================");
    }
}
