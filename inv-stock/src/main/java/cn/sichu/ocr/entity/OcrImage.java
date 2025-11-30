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
 * @since 2025/11/22 21:33
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("ocr_image")
public class OcrImage extends BaseEntity {

    @TableField("file_upload_id")
    private Long fileUploadId;

    @TableField("image_data")
    private byte[] imageData;

    @TableField("upload_by")
    private Long uploadBy;

    @TableField(value = "upload_time", fill = FieldFill.INSERT)
    private LocalDateTime uploadTime;

    /**
     * 0-未处理, 1-已处理, 2-处理失败
     */
    private Integer status = 0;

}
