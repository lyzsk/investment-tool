package cn.sichu.reconcile.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("reconcile_result")
public class ReconcileResult extends BaseEntity {

    /* 同一次对账的行同号 */
    @TableField("batch_no")
    private String batchNo;

    /* MARKET / BILIBILI */
    @TableField("biz_type")
    private String bizType;

    /* 交易日 / UP 名 */
    @TableField("biz_key")
    private String bizKey;

    @TableField("check_item")
    private String checkItem;

    @TableField("expected")
    private String expected;

    @TableField("actual")
    private String actual;

    /* OK / MISSING / FIXED / FAILED / UNRECOVERABLE / WARN */
    @TableField("result")
    private String result;

    @TableField("detail")
    private String detail;
}
