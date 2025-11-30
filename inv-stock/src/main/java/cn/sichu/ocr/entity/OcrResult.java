package cn.sichu.ocr.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDateTime;

/**
 * @author sichu huang
 * @since 2025/11/22 22:35
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("ocr_result")
public class OcrResult extends BaseEntity {

    @TableField("file_upload_id")
    private Long fileUploadId;

    @TableField("raw_text")
    private String rawText;

    @TableField("processed_text")
    private String processedText;

    @TableField("word_count")
    private Long wordCount = 0L;

    @TableField("processed_by")
    private Long processedBy;

    @TableField(value = "process_time", fill = FieldFill.INSERT)
    private LocalDateTime processTime;

    /**
     * 0-成功, 1-失败
     */
    private Integer status = 0;

    @TableField("error_message")
    private String errorMessage;
}
