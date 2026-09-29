package cn.sichu.bilibili.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 *
 * @author sichu huang
 * @since 2026/09/26 20:49
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName(value = "bilibili_video", autoResultMap = true)
public class BilibiliVideo extends BaseEntity {

    @TableField("bvid")
    private String bvid;

    @TableField("author_mid")
    private String authorMid;

    @TableField("title")
    private String title;

    @TableField("publish_time")
    private LocalDateTime publishTime;

    @TableField("trade_date")
    private LocalDate tradeDate;

    @TableField("duration")
    private Integer duration;

    /* B站视频页链接 */
    @TableField("url")
    private String url;

    @TableField("step")
    private String step;

    @TableField("retry_count")
    private Integer retryCount;
}
