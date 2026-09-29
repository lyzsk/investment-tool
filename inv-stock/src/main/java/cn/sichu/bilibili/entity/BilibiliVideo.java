package cn.sichu.bilibili.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Map;

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

    /**
     * 下载产物档案 {mp4, m4a, json 相对路径(正斜杠), meta=抓取元数据全文
     * (bvid/cid/title/pubdate/desc/duration/page/fetched_at)};
     * 物理删除后不置空(2026-09-29 用户定: 路径=曾在哪, meta+bvid=去哪重查;
     * 播放页签名 URL 时效 ~2h, 入库无意义故不存)
     */
    @TableField(value = "source_files", typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> sourceFiles;

    @TableField("step")
    private String step;

    @TableField("retry_count")
    private Integer retryCount;
}
