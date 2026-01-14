package cn.sichu.cls.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDateTime;
import java.util.List;

/**
 * @author sichu huang
 * @since 2026/01/03 16:13
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("cls_telegraph")
public class ClsTelegraph extends BaseEntity {

    @TableField("cls_id")
    private Long clsId;

    @TableField("title")
    private String title;

    @TableField("brief")
    private String brief;

    @TableField("content")
    private String content;

    @TableField("level")
    private String level;

    @TableField("publish_time")
    private LocalDateTime publishTime;

    @TableField("author")
    private String author;

    @TableField(value = "images", typeHandler = JacksonTypeHandler.class)
    private List<String> images;
}
