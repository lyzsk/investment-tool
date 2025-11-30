package cn.sichu.system.controller;

import cn.sichu.system.entity.FileUpload;
import cn.sichu.system.service.IFileUploadService;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import config.ProjectConfig;
import enums.TableLogic;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import result.Result;
import result.ResultCode;
import utils.CollectionUtils;
import utils.StringUtils;
import utils.file.FileUploadUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * @author sichu huang
 * @since 2025/11/30 05:47
 */
@RestController
@RequestMapping("/api/file")
@RequiredArgsConstructor
@Slf4j
public class FileUploadController {
    private final IFileUploadService fileUploadService;
    private final ProjectConfig projectConfig;

    /**
     * 上传单个文件
     * <br/>
     * form-data: file + category
     *
     * @param file     MultipartFile
     * @param category category
     * @return result.Result<cn.sichu.system.entity.FileUpload>
     * @author sichu huang
     * @since 2025/11/30 06:11:55
     */
    @PostMapping("/upload")
    public Result<FileUpload> upload(@RequestParam("file") MultipartFile file,
        @RequestParam(value = "category", required = false, defaultValue = "default")
        String category) {
        if (file.isEmpty()) {
            throw new BusinessException(ResultCode.FILE_EMPTY);
        }
        if (StringUtils.isEmpty(category)) {
            category = "default";
        }
        FileUpload upload = fileUploadService.upload(file, category);
        return Result.success(upload);
    }

    /**
     * 批量上传文件
     * <br/>
     * form-data: files[] + category
     *
     * @param files    List<MultipartFile>
     * @param category category
     * @return result.Result<java.util.List < cn.sichu.system.entity.FileUpload>>
     * @author sichu huang
     * @since 2025/11/30 06:17:55
     */
    @PostMapping("/batch-upload")
    public Result<List<FileUpload>> batchUpload(List<MultipartFile> files, String category) {
        if (CollectionUtils.isEmpty(files)) {
            throw new BusinessException(ResultCode.FILE_EMPTY);
        }
        if (StringUtils.isEmpty(category)) {
            category = "default";
        }
        List<MultipartFile> fileList = new ArrayList<>();
        for (MultipartFile file : files) {
            if (!file.isEmpty()) {
                fileList.add(file);
            }
        }
        List<FileUpload> records = fileUploadService.batchUpload(fileList, category);
        return Result.success(records);
    }

    /**
     * 删除文件(逻辑删除+物理删除)
     *
     * @param fileId fileId
     * @return result.Result<java.lang.Boolean>
     * @author sichu huang
     * @since 2025/11/30 06:30:58
     */
    @DeleteMapping("/delete/{fileId}")
    @Transactional(rollbackFor = Exception.class)
    public Result<Boolean> delete(@PathVariable("fileId") Long fileId) {
        FileUpload fileUpload = fileUploadService.getById(fileId);
        if (fileUpload == null || fileUpload.getIsDeleted() == TableLogic.DELETED.getCode()) {
            throw new BusinessException(ResultCode.FILE_NOT_FOUND);
        }
        boolean physicalDeleted = FileUploadUtils.delete(fileUpload.getPath(), projectConfig);
        if (!physicalDeleted) {
            log.warn("物理删除失败: {}", fileUpload.getPath());
            String currentRemark = fileUpload.getRemark();
            String newRemark = (currentRemark != null ? currentRemark + "; " : "") + "物理删除失败: "
                + fileUpload.getPath();
            fileUpload.setRemark(newRemark);
        }
        LambdaUpdateWrapper<FileUpload> wrapper = new LambdaUpdateWrapper<>();
        wrapper.eq(FileUpload::getId, fileId)
            .eq(FileUpload::getIsDeleted, TableLogic.NOT_DELETED.getCode())
            .set(FileUpload::getDeleteBy, 1L).set(FileUpload::getDeleteTime, LocalDateTime.now())
            .set(FileUpload::getIsDeleted, TableLogic.DELETED.getCode());
        boolean updateResult = fileUploadService.update(wrapper);
        if (!updateResult) {
            log.error("更新删除信息失败: fileId={}", fileId);
            throw new BusinessException("更新删除信息失败");
        }
        boolean logicalDeleted = fileUploadService.removeById(fileId);
        log.info("文件删除成功: fileId={}, 物理删除: {}, 逻辑删除: {}", fileId, physicalDeleted,
            logicalDeleted);
        return Result.success(physicalDeleted);
    }

    /**
     * 批量删除文件(逻辑删除+物理删除)
     *
     * @param fileIds fileIds
     * @return result.Result<java.util.Map < java.lang.String, java.lang.Object>>
     * @author sichu huang
     * @since 2025/11/30 06:54:52
     */
    @DeleteMapping("/batch-delete")
    @Transactional(rollbackFor = Exception.class)
    public Result<Map<String, Object>> batchDelete(@RequestBody List<Long> fileIds) {
        if (CollectionUtils.isEmpty(fileIds)) {
            throw new BusinessException((ResultCode.PARAMS_EMPTY));
        }
        int successCount = 0;
        int failCount = 0;
        List<Long> failIds = new ArrayList<>();
        for (Long fileId : fileIds) {
            try {
                FileUpload fileUpload = fileUploadService.getById(fileId);
                if (fileUpload == null
                    || fileUpload.getIsDeleted() == TableLogic.DELETED.getCode()) {
                    ++failCount;
                    failIds.add(fileId);
                    continue;
                }
                boolean physicalDeleted =
                    FileUploadUtils.delete(fileUpload.getPath(), projectConfig);
                if (!physicalDeleted) {
                    log.warn("物理删除失败: {}, fileId: {}", fileUpload.getPath(), fileId);
                    ++failCount;
                    failIds.add(fileId);
                    String currentRemark = fileUpload.getRemark();
                    String newRemark =
                        (currentRemark != null ? currentRemark + "; " : "") + "物理删除失败: "
                            + fileUpload.getPath();
                    fileUpload.setRemark(newRemark);
                    continue;
                }
                LambdaUpdateWrapper<FileUpload> wrapper = new LambdaUpdateWrapper<>();
                wrapper.eq(FileUpload::getId, fileId)
                    .eq(FileUpload::getIsDeleted, TableLogic.NOT_DELETED.getCode())
                    .set(FileUpload::getDeleteBy, 1L)
                    .set(FileUpload::getDeleteTime, LocalDateTime.now())
                    .set(FileUpload::getIsDeleted, TableLogic.DELETED.getCode());
                boolean updateResult = fileUploadService.update(wrapper);
                if (!updateResult) {
                    log.error("更新删除信息失败: fileId={}", fileId);
                    ++failCount;
                    failIds.add(fileId);
                    continue;
                }
                ++successCount;
            } catch (Exception e) {
                log.error("删除文件失败: fileId: {}", fileId, e);
                ++failCount;
                failIds.add(fileId);
            }
        }
        Map<String, Object> result = new HashMap<>();
        result.put("successCount", successCount);
        result.put("failCount", failCount);
        result.put("failIds", failIds);
        return Result.success(result);
    }
}
