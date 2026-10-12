package cn.sichu.paper.entity;

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
@TableName("chain_decision_rule")
public class ChainDecisionRule extends BaseEntity {

    @TableField("decision_id")
    private Long decisionId;

    @TableField("run_id")
    private Long runId;

    @TableField("skill")
    private String skill;

    @TableField("rule_id")
    private String ruleId;

    @TableField("ctx")
    private String ctx;
}
