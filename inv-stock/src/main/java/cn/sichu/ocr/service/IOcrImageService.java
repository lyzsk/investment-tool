package cn.sichu.ocr.service;

import cn.sichu.ocr.entity.OcrImage;
import com.baomidou.mybatisplus.extension.service.IService;

/**
 * @author sichu huang
 * @since 2025/11/22 21:39
 */
public interface IOcrImageService extends IService<OcrImage> {

    int syncFromFileUpload();

}
