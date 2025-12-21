package cn.sichu.system.quartz.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import enums.BusinessStatus;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * @author sichu huang
 * @since 2025/12/07 02:34
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_job_log")
public class SysJobLog extends BaseEntity {

    @TableField("job_name")
    private String jobName;

    @TableField("job_group")
    private String jobGroup;

    @TableField("job_handler_name")
    private String jobHandlerName;

    @TableField("job_handler_param")
    private String jobHandlerParam;

    @TableField("job_message")
    private String jobMessage;

    @TableField("execution_time")
    private Long executionTime;

    @TableField("exception_message")
    private String exceptionMessage;

    @TableField("status")
    private Integer status = BusinessStatus.SUCCESS.getCode();
}
