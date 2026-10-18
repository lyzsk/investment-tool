package cn.sichu.market.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "kline_minute")
public class KlineMinute extends BaseEntity {

    @TableField("symbol")
    private String symbol;

    @TableField("trade_date")
    private LocalDate tradeDate;

    /* 09:30(含开盘竞价撮合量) + 09:31~11:30 + 13:01~15:00 */
    @TableField("bar_time")
    private LocalDateTime barTime;

    @TableField("open")
    private BigDecimal open;

    @TableField("high")
    private BigDecimal high;

    @TableField("low")
    private BigDecimal low;

    @TableField("close")
    private BigDecimal close;

    /* 本分钟量(非累计) */
    @TableField("volume")
    private Long volume;

    /* 本分钟额(非累计) */
    @TableField("amount")
    private BigDecimal amount;

    /* 分时均价线 */
    @TableField("avg_price")
    private BigDecimal avgPrice;

    @TableField("source")
    private String source;
}
