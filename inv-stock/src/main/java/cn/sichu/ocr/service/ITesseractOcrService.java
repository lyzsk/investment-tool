package cn.sichu.ocr.service;

/**
 * @author sichu huang
 * @since 2025/11/23 03:26
 */
public interface ITesseractOcrService {
    String recognize(byte[] imageBytes);
}
