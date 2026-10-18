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
@TableName(schema = "investment_market", value = "kline_day")
public class KlineDay extends BaseEntity {

    @TableField("symbol")
    private String symbol;

    @TableField("trade_date")
    private LocalDate tradeDate;

    @TableField("open")
    private BigDecimal open;

    @TableField("high")
    private BigDecimal high;

    @TableField("low")
    private BigDecimal low;

    @TableField("close")
    private BigDecimal close;

    /* 昨收: 除权日=除权参考价, 不等于上一行 close */
    @TableField("pre_close")
    private BigDecimal preClose;

    /* 股票/ETF/指数=股, 转债=张 */
    @TableField("volume")
    private Long volume;

    /* 元 */
    @TableField("amount")
    private BigDecimal amount;

    /* 换手率% */
    @TableField("turnover_rate")
    private BigDecimal turnoverRate;

    @TableField("limit_up")
    private BigDecimal limitUp;

    @TableField("limit_down")
    private BigDecimal limitDown;

    @TableField("source")
    private String source;
}
