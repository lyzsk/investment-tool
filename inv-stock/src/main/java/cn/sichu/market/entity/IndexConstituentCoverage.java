package cn.sichu.market.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;

/**
 * 指数成分时点表覆盖范围: 一指数一行; D &gt;= pitFrom 时成分完整, partialFrom &lt;= D &lt; pitFrom 只是当前存活者子集
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "index_constituent_coverage")
public class IndexConstituentCoverage extends BaseEntity {

    @TableField("index_symbol")
    private String indexSymbol;

    @TableField("index_code")
    private String indexCode;

    @TableField("index_name")
    private String indexName;

    /* csindex / cnindex / bse */
    @TableField("publisher")
    private String publisher;

    /* 名义样本数 */
    @TableField("nominal_count")
    private Integer nominalCount;

    /* 完整起点 */
    @TableField("pit_from")
    private LocalDate pitFrom;

    /* 最早有记录日(之前无数据) */
    @TableField("partial_from")
    private LocalDate partialFrom;

    /* 最后一次观测日 */
    @TableField("pit_to")
    private LocalDate pitTo;

    @TableField("method")
    private String method;

    @TableField("source")
    private String source;
}
