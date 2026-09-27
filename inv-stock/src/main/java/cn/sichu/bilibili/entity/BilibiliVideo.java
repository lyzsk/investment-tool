package cn.sichu.bilibili.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

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

    /** B站视频页链接 */
    @TableField("url")
    private String url;

    /** 下载产物相对路径三件套 [mp4, m4a, json](照 cls_telegraph.images 先例), 物理删除后置空 */
    @TableField(value = "source_files", typeHandler = JacksonTypeHandler.class)
    private List<String> sourceFiles;

    @TableField("step")
    private String step;

    @TableField("retry_count")
    private Integer retryCount;
}
