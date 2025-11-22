package cn.sichu.ocr.service.impl;

import cn.sichu.ocr.entity.OcrImage;
import cn.sichu.ocr.mapper.OcrImageMapper;
import cn.sichu.ocr.service.IOcrImageService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.time.LocalDateTime;

/**
 * @author sichu huang
 * @since 2025/11/22 21:40
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class OcrImageServiceImpl extends ServiceImpl<OcrImageMapper, OcrImage>
    implements IOcrImageService {
    @Override
    @Transactional(rollbackFor = Exception.class)
    public OcrImage uploadImage(MultipartFile file) throws IOException {
        OcrImage ocrImage = new OcrImage();
        ocrImage.setFileName(file.getOriginalFilename());
        ocrImage.setFileType(file.getContentType());
        ocrImage.setFileSize(file.getSize());
        ocrImage.setImageData(file.getBytes());
        ocrImage.setUploadTime(LocalDateTime.now());
        this.save(ocrImage);
        return ocrImage;
    }
}
