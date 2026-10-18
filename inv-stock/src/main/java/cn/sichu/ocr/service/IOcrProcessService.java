package cn.sichu.ocr.service;

/**
 * @author sichu huang
 * @since 2025/11/23 00:25
 */
public interface IOcrProcessService {

    /**
     * 从ocr_image表中提取 status = 0(未处理) 且 is_deleted = 0(未删除) 的图片并存入`ocr_result`表中
     *
     * @return int
     * @author sichu huang
     * @since 2025/11/23 04:30:33
     */
    int processPendingImages();

}
