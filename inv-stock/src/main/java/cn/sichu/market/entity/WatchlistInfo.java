package cn.sichu.market.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "watchlist_info")
public class WatchlistInfo extends BaseEntity {

    @TableField("trade_date")
    private LocalDate tradeDate;

    @TableField("symbol")
    private String symbol;

    /* HOLD,PLAN,POOL,MENTOR,ZT,DT,MD,FIXED,STICKY */
    @TableField("reasons")
    private String reasons;

    @TableField("reason_detail")
    private String reasonDetail;

    /* 粘滞保留到哪天 */
    @TableField("sticky_until")
    private LocalDate stickyUntil;
}
