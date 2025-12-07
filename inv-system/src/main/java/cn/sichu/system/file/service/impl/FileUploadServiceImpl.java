package cn.sichu.system.file.service.impl;

import cn.sichu.system.file.dto.FileUploadDto;
import cn.sichu.system.file.entity.FileUpload;
import cn.sichu.system.file.mapper.FileUploadMapper;
import cn.sichu.system.file.service.IFileUploadService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import config.ProjectConfig;
import enums.BusinessStatus;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import result.ResultCode;
import utils.CollectionUtils;
import utils.file.FileUploadUtils;

import java.io.File;
import java.io.IOException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * @author sichu huang
 * @since 2025/11/30 05:36
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class FileUploadServiceImpl extends ServiceImpl<FileUploadMapper, FileUpload>
    implements IFileUploadService {

    private final ProjectConfig projectConfig;

    /**
     * 单文件上传
     *
     * @param file     MultipartFile
     * @param category category
     * @return cn.sichu.system.file.entity.FileUpload
     * @author sichu huang
     * @since 2025/11/30 05:52:17
     */
    @Override
    public FileUpload upload(MultipartFile file, String category) {
        try {
            String relativePath = FileUploadUtils.upload(file, category, projectConfig);
            String savedName = new File(relativePath).getName();
            LocalDateTime now = LocalDateTime.now();
            FileUpload record = new FileUpload();
            record.setOriginalFilename(file.getOriginalFilename());
            record.setSavedFilename(savedName);
            record.setPath(relativePath);
            record.setContentType(file.getContentType());
            record.setSize(file.getSize());
            record.setUploadBy(1L);
            record.setUploadTime(now);
            record.setCategory(category);
            record.setStatus(BusinessStatus.SUCCESS.getCode());
            record.setCreateBy(1L);
            record.setCreateTime(now);
            this.save(record);
            return record;
        } catch (IOException e) {
            throw new BusinessException(ResultCode.FILE_UPLOAD_FAILED);
        }
    }

    /**
     * 批量文件上传
     * <p/>
     * update: 2025/12/06 23:30:47 修改返回对象java.util.List<cn.sichu.system.file.entity.FileUpload> -> cn.sichu.system.dto.BatchUploadDto
     *
     * @param files    List<MultipartFile>
     * @param category category
     * @return cn.sichu.system.dto.BatchUploadDto
     * @author sichu huang
     * @since 2025/11/30 05:52:39
     */
    @Override
    public FileUploadDto batchUpload(List<MultipartFile> files, String category) {
        if (CollectionUtils.isEmpty(files)) {
            return new FileUploadDto(Collections.emptyList(), 0, 0, Collections.emptyList());
        }
        List<FileUpload> successFiles = new ArrayList<>();
        List<String> failFilenames = new ArrayList<>();
        for (MultipartFile file : files) {
            if (file == null || file.isEmpty()) {
                continue;
            }
            try {
                FileUpload fileUpload = upload(file, category);
                successFiles.add(fileUpload);
            } catch (Exception e) {
                log.warn("批量上传中单个文件失败: {}", file.getOriginalFilename(), e);
                failFilenames.add(file.getOriginalFilename());
            }
        }
        return new FileUploadDto(successFiles, successFiles.size(), failFilenames.size(),
            failFilenames);
    }
}
