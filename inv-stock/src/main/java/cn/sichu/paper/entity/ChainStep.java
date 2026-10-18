package cn.sichu.paper.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDateTime;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("chain_step")
public class ChainStep extends BaseEntity {

    @TableField("run_id")
    private Long runId;

    /* 01/02/03b/03s/03j/04/05/06/blind/07 */
    @TableField("step")
    private String step;

    @TableField("file_name")
    private String fileName;

    @TableField("file_mtime")
    private LocalDateTime fileMtime;

    @TableField("bytes")
    private Integer bytes;

    @TableField("sha12")
    private String sha12;

    @TableField("sentinel_ok")
    private Integer sentinelOk;

    /* json 列 */
    @TableField("contract_json")
    private String contractJson;

    @TableField("contract_error")
    private String contractError;
}
