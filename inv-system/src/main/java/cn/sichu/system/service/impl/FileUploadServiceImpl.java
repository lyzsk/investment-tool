package cn.sichu.system.service.impl;

import cn.sichu.system.entity.FileUpload;
import cn.sichu.system.mapper.FileUploadMapper;
import cn.sichu.system.service.IFileUploadService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import config.ProjectConfig;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import result.ResultCode;
import utils.file.FileUploadUtils;

import java.io.File;
import java.io.IOException;
import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.Collectors;

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
     * @return cn.sichu.system.entity.FileUpload
     * @author sichu huang
     * @since 2025/11/30 05:52:17
     */
    @Override
    public FileUpload upload(MultipartFile file, String category) {
        try {
            String relativePath = FileUploadUtils.upload(file, category, projectConfig);
            String savedName = new File(relativePath).getName();
            FileUpload record = new FileUpload();
            record.setOriginalFilename(file.getOriginalFilename());
            record.setSavedFilename(savedName);
            record.setPath(relativePath);
            record.setContentType(file.getContentType());
            record.setSize(file.getSize());
            record.setUploadBy(1L);
            record.setUploadTime(LocalDateTime.now());
            record.setCategory(category);
            this.save(record);
            return record;
        } catch (IOException e) {
            throw new BusinessException(ResultCode.FILE_UPLOAD_FAILED);
        }
    }

    /**
     * 批量文件上传
     *
     * @param files    List<MultipartFile>
     * @param category category
     * @return java.util.List<cn.sichu.system.entity.FileUpload>
     * @author sichu huang
     * @since 2025/11/30 05:52:39
     */
    @Override
    public List<FileUpload> batchUpload(List<MultipartFile> files, String category) {
        return files.stream().map(file -> upload(file, category)).collect(Collectors.toList());
    }
}
