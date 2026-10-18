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
@TableName(schema = "investment_market", value = "security_master")
public class SecurityMaster extends BaseEntity {

    /* 市场前缀+代码: sh600519 / sz399006 / bj920985 / sh113052 */
    @TableField("symbol")
    private String symbol;

    /* 纯代码(不带前缀) */
    @TableField("code")
    private String code;

    /* SH/SZ/BJ/HK/EM/US/JP/KR/GLOBAL */
    @TableField("exchange")
    private String exchange;

    /* STOCK/CB/ETF/INDEX/BOARD/OTHER */
    @TableField("sec_type")
    private String secType;

    /* STOCK: MAIN/GEM/STAR/BSE/HKC; BOARD: INDUSTRY/CONCEPT/REGION */
    @TableField("board_type")
    private String boardType;

    @TableField("name")
    private String name;

    @TableField("is_st")
    private Integer isSt;

    @TableField("list_date")
    private LocalDate listDate;

    @TableField("delist_date")
    private LocalDate delistDate;

    /* 仅转债: 正股 symbol */
    @TableField("underlying_symbol")
    private String underlyingSymbol;

    @TableField("source")
    private String source;
}
