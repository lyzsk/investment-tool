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
import utils.StringUtils;
import utils.file.FileUploadUtils;
import utils.file.FileUtils;

import java.io.File;
import java.io.IOException;
import java.time.LocalDateTime;
import java.util.*;
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
            return new FileUploadDto(Collections.emptyList(), 0, 0, Collections.emptyList(),
                Collections.emptyList());
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
            failFilenames, Collections.emptyList());
    }

    /**
     * 从本地目录批量上传文件
     * <p/>
     * 如果入参contentType和文件扩展名匹配 && 文件扩展名在yml配置的合法扩展名中, 上传, 否则跳过
     *
     * @param category    category
     * @param path        path
     * @param contentType contentType
     * @return cn.sichu.system.file.dto.FileUploadDto
     * @author sichu huang
     * @since 2025/12/14 07:46:31
     */
    @Override
    public FileUploadDto batchUploadFromLocal(String category, String path, String contentType) {
        File dir = new File(path);
        if (!dir.exists() || !dir.isDirectory()) {
            throw new BusinessException(ResultCode.INVALID_PATH);
        }
        /* 标准化contentType */
        String extesion = contentType.toLowerCase();
        if (extesion.startsWith(StringUtils.DOT)) {
            extesion = FileUtils.getFileExtension(extesion);
        }
        Set<String> allowedExts =
            FileUtils.mimeTypeToExtesions(projectConfig.getFile().getAllowedTypes());
        File[] files = dir.listFiles();
        if (files == null || files.length == 0) {
            return new FileUploadDto(Collections.emptyList(), 0, 0, Collections.emptyList(),
                Collections.emptyList());
        }
        List<MultipartFile> list = new ArrayList<>();
        List<String> skippedFilenames = new ArrayList<>();
        for (File file : files) {
            if (!file.isFile()) {
                skippedFilenames.add(file.getName());
                continue;
            }
            String fileExtension = FileUtils.getFileExtension(file.getName());
            if (extesion.equals(fileExtension) && allowedExts.contains(fileExtension)) {
                try {
                    MultipartFile multipartFile = FileUtils.toMultipartFile(file);
                    list.add(multipartFile);
                } catch (IllegalAccessException e) {
                    skippedFilenames.add(file.getName());
                }
            } else {
                skippedFilenames.add(file.getName());
            }
        }
        FileUploadDto fileUploadDto = batchUpload(list, category);
        FileUploadDto result =
            new FileUploadDto(fileUploadDto.successList(), fileUploadDto.successCount(),
                fileUploadDto.failCount(), fileUploadDto.failFilenames(), skippedFilenames);
        log.info(
            "批量上传完成 | 路径: {} | 扩展名: {} | 总文件数: {} | 成功: {} | 失败: {} | 跳过: {}",
            path, extesion, files.length, result.successCount(), result.failCount(),
            skippedFilenames.size());
        return result;
    }

    /**
     * 批量上传本地目录下指定扩展名的文件
     *
     * @param category   category
     * @param path       绝对路径
     * @param extensions 用逗号分割的合法扩展名
     * @return cn.sichu.system.file.dto.FileUploadDto
     * @author sichu huang
     * @since 2025/12/14 09:06:39
     */
    @Override
    public FileUploadDto batchUploadFromPathWithExtensions(String category, String path,
        String extensions) {
        File dir = new File(path);
        if (!dir.exists() || !dir.isDirectory()) {
            throw new BusinessException(ResultCode.INVALID_PATH);
        }
        if (StringUtils.isEmpty(extensions)) {
            return new FileUploadDto(Collections.emptyList(), 0, 0, Collections.emptyList(),
                Collections.emptyList());
        }
        Set<String> extSet = Arrays.stream(extensions.split(StringUtils.COMMA)).map(String::trim)
            .filter(ext -> !ext.isEmpty()).map(ext -> {
                if (ext.startsWith(StringUtils.DOT)) {
                    return FileUtils.getFileExtension(ext);
                }
                return ext.toLowerCase();
            }).collect(Collectors.toCollection(LinkedHashSet::new));
        if (extSet.isEmpty()) {
            log.warn("批量上传文件失败, 入参extensions为空或不是用逗号分割的合法扩展名: {}",
                extensions);
            return new FileUploadDto(Collections.emptyList(), 0, 0, Collections.emptyList(),
                Collections.emptyList());
        }

        Set<String> allowedExts =
            FileUtils.mimeTypeToExtesions(projectConfig.getFile().getAllowedTypes());
        Set<String> validExts =
            extSet.stream().filter(allowedExts::contains).collect(Collectors.toSet());
        File[] files = dir.listFiles();
        if (files == null || files.length == 0) {
            return new FileUploadDto(Collections.emptyList(), 0, 0, Collections.emptyList(),
                Collections.emptyList());
        }
        List<MultipartFile> list = new ArrayList<>();
        List<String> skippedFilenames = new ArrayList<>();
        for (File file : files) {
            if (!file.isFile()) {
                skippedFilenames.add(file.getName());
                continue;
            }
            String fileExt = FileUtils.getFileExtension(file.getName());
            if (validExts.contains(fileExt)) {
                try {
                    MultipartFile multipartFile = FileUtils.toMultipartFile(file);
                    list.add(multipartFile);
                } catch (IllegalAccessException e) {
                    skippedFilenames.add(file.getName());
                }
            } else {
                skippedFilenames.add(file.getName());
            }
        }
        FileUploadDto fileUploadDto = batchUpload(list, category);
        FileUploadDto result =
            new FileUploadDto(fileUploadDto.successList(), fileUploadDto.successCount(),
                fileUploadDto.failCount(), fileUploadDto.failFilenames(), skippedFilenames);
        log.info(
            "批量上传完成 | 路径: {} | 扩展名: {} | 总文件数: {} | 成功: {} | 失败: {} | 跳过: {}",
            path, String.join(",", extSet), files.length, result.successCount(), result.failCount(),
            skippedFilenames.size());
        return result;
    }
}
