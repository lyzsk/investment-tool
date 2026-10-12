package cn.sichu.paper.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("chain_decision")
public class ChainDecision extends BaseEntity {

    @TableField("run_id")
    private Long runId;

    @TableField("skill")
    private String skill;

    @TableField("run_date")
    private LocalDate runDate;

    @TableField("slot")
    private String slot;

    @TableField("action_idx")
    private Integer actionIdx;

    @TableField("name")
    private String name;

    @TableField("code")
    private String code;

    @TableField("op")
    private String op;

    /* 可能是公式 Z*0.97 */
    @TableField("trigger_price")
    private String triggerPrice;

    @TableField("qty")
    private Integer qty;

    @TableField("anchor")
    private String anchor;

    @TableField("cancel_below")
    private BigDecimal cancelBelow;

    @TableField("stop_below")
    private BigDecimal stopBelow;

    @TableField("invalid_if")
    private String invalidIf;

    /* json 列 */
    @TableField("action_json")
    private String actionJson;
}
