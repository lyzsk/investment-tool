package cn.sichu.system.quartz.entity;

import base.BaseEntity;
import cn.sichu.system.quartz.enums.MisfirePolicy;
import cn.sichu.system.quartz.enums.QuartzStatus;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * @author sichu huang
 * @since 2025/12/07 02:08
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_job")
public class SysJob extends BaseEntity {

    @TableField("job_name")
    private String jobName;

    @TableField("job_group")
    private String jobGroup;

    @TableField("job_handler_name")
    private String jobHandlerName;

    @TableField("job_handler_param")
    private String jobHandlerParam;

    @TableField("retry_count")
    private Integer retryCount;

    @TableField("retry_interval")
    private Integer retryInterval;

    @TableField("cron_expression")
    private String cronExpression;

    /**
     * 0-立即执行, 1-执行一次, 2-放弃执行
     */
    @TableField("misfire_policy")
    private Integer misfirePolicy = MisfirePolicy.ABADON_EXECUTION.getCode();

    /**
     * 0-运行, 1-暂停
     */
    @TableField("status")
    private Integer status = QuartzStatus.PAUSED.getCode();
}
