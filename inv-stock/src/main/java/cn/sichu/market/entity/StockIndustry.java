package cn.sichu.market.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;

/**
 * 个股行业时点区间(申万优先, 证监会兜底): 一行 = [inDate, outDate) 内的行业归属
 * 由 scripts/market/index_constituents.py 整表重建, Java 只读
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "stock_industry")
public class StockIndustry extends BaseEntity {

    @TableField("symbol")
    private String symbol;

    @TableField("code")
    private String code;

    /* SW / CSRC */
    @TableField("classification")
    private String classification;

    /* SW2021 / SW2014 / SW_OLD / CSRC2012 */
    @TableField("version")
    private String version;

    /* 原始行业代码: 申万 6 位三级码 / 证监会 门类+大类 */
    @TableField("ind_code")
    private String indCode;

    @TableField("l1_code")
    private String l1Code;

    @TableField("l1_name")
    private String l1Name;

    @TableField("l2_code")
    private String l2Code;

    @TableField("l2_name")
    private String l2Name;

    /* 仅申万 */
    @TableField("l3_code")
    private String l3Code;

    /* 仅申万 */
    @TableField("l3_name")
    private String l3Name;

    /* 归属生效日(含) */
    @TableField("in_date")
    private LocalDate inDate;

    /* 归属失效日(不含); null=当前归属 */
    @TableField("out_date")
    private LocalDate outDate;

    /* 1-真实生效日(证监会为月粒度); 0-左删失 */
    @TableField("in_exact")
    private Integer inExact;

    /* swsresearch / baostock */
    @TableField("source")
    private String source;
}
