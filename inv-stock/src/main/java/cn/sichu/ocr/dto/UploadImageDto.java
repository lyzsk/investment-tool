package cn.sichu.ocr.dto;

import lombok.Data;
import org.springframework.web.multipart.MultipartFile;

/**
 * @author sichu huang
 * @since 2025/11/22 21:35
 */
@Data
public class UploadImageDto {

    /* Postman 用 form-data 时必须这样接收, key=file */
    private MultipartFile file;
}
