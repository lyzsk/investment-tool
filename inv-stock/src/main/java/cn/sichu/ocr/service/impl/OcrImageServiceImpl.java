package cn.sichu.ocr.service.impl;

import cn.sichu.ocr.entity.OcrImage;
import cn.sichu.ocr.mapper.OcrImageMapper;
import cn.sichu.ocr.service.IOcrImageService;
import cn.sichu.system.file.entity.FileUpload;
import cn.sichu.system.file.mapper.FileUploadMapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import config.ProjectConfig;
import enums.ProcessStatus;
import enums.TableLogic;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import result.ResultCode;
import utils.StringUtils;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.time.LocalDateTime;
import java.util.List;

/**
 * @author sichu huang
 * @since 2025/11/22 21:40
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class OcrImageServiceImpl extends ServiceImpl<OcrImageMapper, OcrImage>
    implements IOcrImageService {

    private final FileUploadMapper fileUploadMapper;
    private final ProjectConfig projectConfig;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public int syncFromFileUpload() {
        /* 查询 `file_upload` 表中 category='ocr' 且未逻辑删除的文件 */
        List<FileUpload> list = fileUploadMapper.selectByCategoryAndNotDeleted("ocr");
        int syncedCount = 0;
        for (FileUpload fileUpload : list) {
            if (!isImageType(fileUpload.getContentType())) {
                log.warn("跳过非图片文件: fileUploadId={}, contentType={}", fileUpload.getId(),
                    fileUpload.getContentType());
                continue;
            }
            if (!isSupportedImageType(fileUpload.getContentType())) {
                log.error(ResultCode.IMAGE_TYPE_NOT_SUPPORTED.getCode()
                        + "{} fileUploadId={}, contentType={}",
                    ResultCode.IMAGE_TYPE_NOT_SUPPORTED.getMsg(), fileUpload.getId(),
                    fileUpload.getContentType());
                continue;
            }
            /* 检查是否已同步过 */
            boolean exists = this.count(Wrappers.lambdaQuery(OcrImage.class)
                .eq(OcrImage::getFileUploadId, fileUpload.getId())
                .eq(OcrImage::getIsDeleted, TableLogic.NOT_DELETED.getCode())) > 0;

            if (!exists) {
                OcrImage ocrImage = new OcrImage();
                ocrImage.setFileUploadId(fileUpload.getId());
                /* 读取fileUpload内容并设置到 `image_data` 字段 */
                byte[] imageData = readImageFile(fileUpload.getPath());
                ocrImage.setImageData(imageData);
                ocrImage.setUploadBy(1L);
                ocrImage.setUploadTime(fileUpload.getUploadTime());
                ocrImage.setStatus(ProcessStatus.UNPROCESSED.getCode());
                ocrImage.setCreateBy(1L);
                ocrImage.setCreateTime(LocalDateTime.now());
                this.save(ocrImage);
                ++syncedCount;
                log.info("同步OCR文件成功: fileUploadId={}, ocrImageId={}", fileUpload.getId(),
                    ocrImage.getId());
            }
        }
        log.info("OCR文件同步完成，共同步 {} 条记录", syncedCount);
        return syncedCount;
    }

    private boolean isImageType(String contentType) {
        if (StringUtils.isEmpty(contentType)) {
            return false;
        }
        return contentType.toLowerCase().startsWith("image/");
    }

    private boolean isSupportedImageType(String contentType) {
        if (StringUtils.isEmpty(contentType)) {
            return false;
        }
        return projectConfig.getFile().getAllowedTypes().stream()
            .anyMatch(allowedType -> contentType.toLowerCase().equals(allowedType));

    }

    private byte[] readImageFile(String relativePath) {
        if (relativePath == null) {
            throw new BusinessException(ResultCode.FILE_PATH_NOT_FOUND);
        }
        String absolutePath = projectConfig.getFile().getRootDir() + relativePath;
        File file = new File(absolutePath);
        if (!file.exists()) {
            throw new BusinessException(ResultCode.FILE_NOT_FOUND + ": " + absolutePath);
        }
        try {
            return Files.readAllBytes(file.toPath());
        } catch (IOException e) {
            throw new BusinessException(ResultCode.FAILED_TO_READ_FILE + ": " + absolutePath, e);
        }
    }
}
