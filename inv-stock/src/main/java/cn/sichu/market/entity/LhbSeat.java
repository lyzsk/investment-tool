package cn.sichu.market.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * 龙虎榜席位明细: 一行=某条上榜记录买五或卖五里的一个席位(东财原样), 同席位同在买五卖五=两行
 *
 * @author sichu huang
 * @since 2026/10/15
 **/
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(schema = "investment_market", value = "lhb_seat")
public class LhbSeat extends BaseEntity {

    @TableField("trade_date")
    private LocalDate tradeDate;

    @TableField("symbol")
    private String symbol;

    @TableField("code")
    private String code;

    /* 见 lhb_stock.trade_id */
    @TableField("trade_id")
    private Long tradeId;

    /* BUY-买五席位, SELL-卖五席位 */
    @TableField("direction")
    private String direction;

    /* 该方向内名次(1~5, 按该方向金额降序) */
    @TableField("seat_rank")
    private Integer seatRank;

    /* 东财营业部编码 */
    @TableField("dept_code")
    private String deptCode;

    /* 营业部全名(东财原文) */
    @TableField("dept_name")
    private String deptName;

    /* 该方向金额(元): BUY=买入额, SELL=卖出额 */
    @TableField("amount")
    private BigDecimal amount;

    @TableField("buy_amt")
    private BigDecimal buyAmt;

    @TableField("sell_amt")
    private BigDecimal sellAmt;

    @TableField("net_amt")
    private BigDecimal netAmt;

    /* 买入额占当日总成交比(小数) */
    @TableField("buy_ratio")
    private BigDecimal buyRatio;

    /* 卖出额占当日总成交比(小数) */
    @TableField("sell_ratio")
    private BigDecimal sellRatio;

    /* 1-机构席位, 0-否 */
    @TableField("is_institution")
    private Integer isInstitution;

    /* 游资别名(youzi.json 对照), 未收录=null */
    @TableField("youzi_alias")
    private String youziAlias;

    @TableField("source")
    private String source;
}
