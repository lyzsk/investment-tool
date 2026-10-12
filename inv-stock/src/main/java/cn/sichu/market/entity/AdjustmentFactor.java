package cn.sichu.market.entity;

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
 * @since 2026/10/11
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "adjustment_factor")
public class AdjustmentFactor extends BaseEntity {

    @TableField("symbol")
    private String symbol;

    /* 因子生效日(除权除息日; 首行=上市日) */
    @TableField("ex_date")
    private LocalDate exDate;

    /* 累积复权因子(后复权口径) */
    @TableField("factor")
    private BigDecimal factor;

    @TableField("source")
    private String source;
}
