package cn.sichu.annotation;

import java.lang.annotation.*;

/**
 * @author sichu huang
 * @date 2024/05/02
 **/
@Target({ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface LogAnnotation {

    String module() default "";

    String operation() default "";
}
