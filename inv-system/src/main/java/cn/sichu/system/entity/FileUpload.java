package cn.sichu.system.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDateTime;

/**
 * @author sichu huang
 * @since 2025/11/30 05:16
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("file_upload")
public class FileUpload extends BaseEntity {

    @TableField("original_filename")
    private String originalFilename;

    @TableField("saved_filename")
    private String SavedFilename;

    private String path;

    @TableField("content_type")
    private String contentType;

    private Long size;

    @TableField("upload_by")
    private Long uploadBy;

    @TableField(value = "upload_time", fill = FieldFill.INSERT)
    private LocalDateTime uploadTime;

    private String category;
}
