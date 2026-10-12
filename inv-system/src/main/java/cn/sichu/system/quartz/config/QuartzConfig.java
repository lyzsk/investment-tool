package cn.sichu.system.quartz.config;

import org.quartz.spi.JobFactory;
import org.quartz.spi.TriggerFiredBundle;
import org.springframework.beans.factory.config.AutowireCapableBeanFactory;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationContextAware;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.quartz.SchedulerFactoryBean;
import org.springframework.scheduling.quartz.SpringBeanJobFactory;

/**
 * @author sichu huang
 * @since 2025/12/21 01:23
 */
@Configuration
public class QuartzConfig {
    @Bean
    public JobFactory jobFactory(ApplicationContext applicationContext) {
        AutowiringSpringBeanJobFactory jobFactory = new AutowiringSpringBeanJobFactory();
        jobFactory.setApplicationContext(applicationContext);
        return jobFactory;
    }

    @Bean
    public SchedulerFactoryBean schedulerFactoryBean(JobFactory jobFactory) {
        SchedulerFactoryBean schedulerFactory = new SchedulerFactoryBean();
        schedulerFactory.setJobFactory(jobFactory);
        /* 10/11: 自建 SchedulerFactoryBean 不吃 yml 的 spring.quartz 配置, 原为 Quartz 默认 10 线程+5s misfire 阈值——
           盘前 15 条 paper 链(各占线程 45min+)+每分钟撮合+CLS 5 分钟同时起, 线程不够=链被静默丢弃、撮合被饿死。
           40 线程; misfire 阈值 10min(排队超 10min 才算错过, 期间等到线程即执行) */
        java.util.Properties props = new java.util.Properties();
        props.setProperty("org.quartz.threadPool.threadCount", "40");
        props.setProperty("org.quartz.jobStore.misfireThreshold", "600000");
        schedulerFactory.setQuartzProperties(props);
        return schedulerFactory;
    }

    /**
     * 内部类 支持 Spring 自动装配的 JobFactory
     *
     * @author sichu huang
     * @since 2025/12/21 01:25:54
     */
    public static class AutowiringSpringBeanJobFactory extends SpringBeanJobFactory
        implements ApplicationContextAware {
        private transient AutowireCapableBeanFactory beanFactory;

        @Override
        public void setApplicationContext(final ApplicationContext context) {
            beanFactory = context.getAutowireCapableBeanFactory();
        }

        @Override
        protected Object createJobInstance(final TriggerFiredBundle bundle) throws Exception {
            final Object job = super.createJobInstance(bundle);
            beanFactory.autowireBean(job);
            return job;
        }
    }
}
