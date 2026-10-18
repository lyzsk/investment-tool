package cn.sichu.ocr.service;

import cn.sichu.ocr.entity.OcrImage;
import com.baomidou.mybatisplus.extension.service.IService;

/**
 * @author sichu huang
 * @since 2025/11/22 21:39
 */
public interface IOcrImageService extends IService<OcrImage> {

    /**
     * 从`file_upload`表中同步文件到`ocr_image`表中
     *
     * @return int 成功同步个数
     * @author sichu huang
     * @since 2025/12/20 20:47:48
     */
    int syncFromFileUpload();

}
