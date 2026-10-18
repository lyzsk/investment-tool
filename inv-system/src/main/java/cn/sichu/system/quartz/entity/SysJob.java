package cn.sichu.system.quartz.entity;

import base.BaseEntity;
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
     * <p>10/17 晚 审计② Q-4: 去掉字段默认值——原来 /update 只传 id+cron 时, 反序列化出的对象带着默认值 status=1(暂停)、
     * misfire=2 去覆盖库里的值, 任务被悄悄暂停。默认值改在新增(saveJob)时补, 更新时 null=沿用库里原值
     */
    @TableField("misfire_policy")
    private Integer misfirePolicy;

    /**
     * 0-运行, 1-暂停(新增时不传=暂停)
     */
    @TableField("status")
    private Integer status;
}
