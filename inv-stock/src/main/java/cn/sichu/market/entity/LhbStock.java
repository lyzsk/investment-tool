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
 * 龙虎榜上榜明细: 一行=东财一条上榜记录(TRADE_ID), 一只票一天可多条
 *
 * @author sichu huang
 * @since 2026/10/15
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "lhb_stock")
public class LhbStock extends BaseEntity {

    @TableField("trade_date")
    private LocalDate tradeDate;

    @TableField("symbol")
    private String symbol;

    /* 6 位证券代码 */
    @TableField("code")
    private String code;

    @TableField("name")
    private String name;

    /* 东财上榜记录 ID, 与 lhb_seat.trade_id 关联 */
    @TableField("trade_id")
    private Long tradeId;

    /* 1-主记录(当日口径优先, 只有多日累计榜时取它), 0-同票同日其他记录 */
    @TableField("is_primary")
    private Integer isPrimary;

    /* 上榜原因(东财原文) */
    @TableField("reason")
    private String reason;

    @TableField("close_price")
    private BigDecimal closePrice;

    /* 涨跌幅(%) */
    @TableField("change_rate")
    private BigDecimal changeRate;

    /* 买五卖五合计买入额(元) */
    @TableField("buy_amt")
    private BigDecimal buyAmt;

    /* 买五卖五合计卖出额(元) */
    @TableField("sell_amt")
    private BigDecimal sellAmt;

    /* 龙虎榜净额(元) */
    @TableField("net_amt")
    private BigDecimal netAmt;

    /* 净额占当日总成交额比(%) */
    @TableField("deal_net_ratio")
    private BigDecimal dealNetRatio;

    /* 当日总成交额(元); 多日累计榜=累计期成交额 */
    @TableField("deal_amount")
    private BigDecimal dealAmount;

    /* 换手率(%) */
    @TableField("turnover_rate")
    private BigDecimal turnoverRate;

    /* 东财 TRADE_MARKET, 如 深交所创业板 */
    @TableField("trade_market")
    private String tradeMarket;

    /* 原始数据抓取时刻(北京时间) */
    @TableField("fetched_at")
    private LocalDateTime fetchedAt;

    /* em / ths */
    @TableField("source")
    private String source;
}
