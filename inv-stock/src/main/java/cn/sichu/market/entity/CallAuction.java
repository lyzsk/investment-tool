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
@TableName(schema = "investment_market", value = "call_auction")
public class CallAuction extends BaseEntity {
    
    @TableField("symbol")
    private String symbol;

    @TableField("trade_date")
    private LocalDate tradeDate;

    /* OPEN / CLOSE */
    @TableField("phase")
    private String phase;

    @TableField("snap_time")
    private LocalDateTime snapTime;

    /* 虚拟匹配价; 每段最后一行=撮合成交价 */
    @TableField("price")
    private BigDecimal price;

    @TableField("matched_volume")
    private Long matchedVolume;

    @TableField("matched_amount")
    private BigDecimal matchedAmount;

    /* 正=买方剩余, 负=卖方剩余(口径待实测) */
    @TableField("unmatched_volume")
    private Long unmatchedVolume;

    @TableField("source")
    private String source;
}
