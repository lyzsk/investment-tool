package cn.sichu.ocr.service;

import cn.sichu.ocr.entity.OcrImage;
import com.baomidou.mybatisplus.extension.service.IService;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;

/**
 * @author sichu huang
 * @since 2025/11/22 21:39
 */
public interface IOcrImageService extends IService<OcrImage> {
    OcrImage uploadImage(MultipartFile file) throws IOException;

}
