package cn.sichu.paper.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("chain_run")
public class ChainRun extends BaseEntity {

    /* taoge/buchitudou0/.../control */
    @TableField("skill")
    private String skill;

    /* LIVE / ASOF */
    @TableField("mode")
    private String mode;

    @TableField("run_date")
    private LocalDate runDate;

    /* HHMM / review / FINAL */
    @TableField("slot")
    private String slot;

    @TableField("run_dir")
    private String runDir;

    @TableField("exit_code")
    private Integer exitCode;

    @TableField("started_at")
    private LocalDateTime startedAt;

    @TableField("finished_at")
    private LocalDateTime finishedAt;

    @TableField("duration_s")
    private Integer durationS;

    @TableField("steps")
    private String steps;

    @TableField("market_state")
    private String marketState;

    @TableField("leading_layer")
    private String leadingLayer;

    @TableField("debate_winner")
    private String debateWinner;

    @TableField("blind_verdict")
    private String blindVerdict;

    @TableField("blind_failed")
    private Integer blindFailed;

    @TableField("no_trade")
    private Integer noTrade;

    @TableField("action_count")
    private Integer actionCount;

    @TableField("rules_count")
    private Integer rulesCount;

    @TableField("chain_md_sha12")
    private String chainMdSha12;

    /* json 列 */
    @TableField("persona_json")
    private String personaJson;
}
