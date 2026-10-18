package cn.sichu.market.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;

/**
 * 指数成分时点区间: 一行 = [inDate, outDate) 半开区间; 日期 D 是成分 ⇔ inDate &lt;= D 且 (outDate 为空或 &gt; D)
 * 由 scripts/market/index_constituents.py 整表重建, Java 只读
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "index_constituent")
public class IndexConstituent extends BaseEntity {

    /* 指数 symbol: sh000300 / sz399006 / bj899050 / csi932000(中证官网独有指数) */
    @TableField("index_symbol")
    private String indexSymbol;

    @TableField("index_code")
    private String indexCode;

    @TableField("index_name")
    private String indexName;

    /* 成分股 symbol(同 security_master) */
    @TableField("con_symbol")
    private String conSymbol;

    @TableField("con_code")
    private String conCode;

    /* 区间首次观测到时的简称 */
    @TableField("con_name")
    private String conName;

    /* 纳入生效日(含) */
    @TableField("in_date")
    private LocalDate inDate;

    /* 剔除生效日(不含); null=至今仍在 */
    @TableField("out_date")
    private LocalDate outDate;

    /* 1-真实纳入日; 0-左删失(覆盖起点已在指数里) */
    @TableField("in_exact")
    private Integer inExact;

    /* baostock / cnindex / sina, 可带 +sina_date / +inferred / +censored 等后缀 */
    @TableField("source")
    private String source;
}
