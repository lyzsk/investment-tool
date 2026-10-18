package cn.sichu.tzzb.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

/**
 *
 * @author sichu huang
 * @since 2026/10/01 23:40
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(value = "tzzb_record", autoResultMap = true)
public class TzzbRecord extends BaseEntity {

    @TableField("ledger")
    private String ledger;

    @TableField("record_type")
    private String recordType;

    @TableField("record_time")
    private LocalDateTime recordTime;

    @TableField("stock_code")
    private String stockCode;

    @TableField("stock_name")
    private String stockName;

    @TableField("side")
    private String side;

    @TableField("price")
    private BigDecimal price;

    @TableField("qty")
    private BigDecimal qty;

    @TableField("amount")
    private BigDecimal amount;

    @TableField("daily_return_pct")
    private BigDecimal dailyReturnPct;

    @TableField(value = "payload_json", typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> payloadJson;
}
