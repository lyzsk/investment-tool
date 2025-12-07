package cn.sichu.system.file.controller;

import cn.sichu.system.file.dto.FileDeleteDto;
import cn.sichu.system.file.dto.FileUploadDto;
import cn.sichu.system.file.entity.FileUpload;
import cn.sichu.system.file.service.IFileUploadService;
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
import utils.DateUtils;
import utils.StringUtils;
import utils.file.FileUploadUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

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

    private static FileDeleteDto getFileDeleteDto(Long fileId, boolean logicalDeleted,
        boolean physicalDeleted) {
        FileDeleteDto result = new FileDeleteDto();
        if (logicalDeleted) {
            result.setLogicalSuccessCount(1);
            result.setPhysicalSuccessCount(physicalDeleted ? 1 : 0);
            if (!physicalDeleted) {
                result.setFailCount(1);
                result.setIncompleteOrFailedIds(List.of(fileId));
            } else {
                result.setFailCount(0);
                result.setIncompleteOrFailedIds(new ArrayList<>());
            }
        } else {
            result.setLogicalSuccessCount(0);
            result.setPhysicalSuccessCount(0);
            result.setFailCount(1);
            result.setIncompleteOrFailedIds(List.of(fileId));
        }
        return result;
    }

    /**
     * 上传单个文件
     * <br/>
     * form-data: file + category
     * <p/>
     * update: 2025/12/07 00:20:53 修改返回类型
     *
     * @param file     MultipartFile
     * @param category category
     * @return result.Result<cn.sichu.system.dto.FileUploadDto>
     * @author sichu huang
     * @since 2025/11/30 06:11:55
     */
    @PostMapping("/upload")
    public Result<FileUploadDto> upload(@RequestParam("file") MultipartFile file,
        @RequestParam(value = "category", required = false, defaultValue = "default")
        String category) {
        if (file.isEmpty()) {
            throw new BusinessException(ResultCode.FILE_EMPTY);
        }
        if (StringUtils.isEmpty(category)) {
            category = "default";
        }
        FileUpload upload = fileUploadService.upload(file, category);
        FileUploadDto dto = new FileUploadDto();
        dto.setSuccessList(List.of(upload));
        dto.setSuccessCount(1);
        dto.setFailCount(0);
        dto.setFailFilenames(new ArrayList<>());
        return Result.success(dto);
    }

    /**
     * 批量上传文件
     * <br/>
     * form-data: files[] + category
     * <p/>
     * update: 2025/12/06 23:39:33 修改返回类型
     *
     * @param files    List<MultipartFile>
     * @param category category
     * @return result.Result<cn.sichu.system.dto.FileUploadDto>
     * @author sichu huang
     * @since 2025/11/30 06:17:55
     */
    @PostMapping("/batch-upload")
    public Result<FileUploadDto> batchUpload(@RequestParam("files") List<MultipartFile> files,
        @RequestParam(value = "category", required = false, defaultValue = "default")
        String category) {
        if (CollectionUtils.isEmpty(files)) {
            throw new BusinessException(ResultCode.FILE_EMPTY);
        }
        if (StringUtils.isEmpty(category)) {
            category = "default";
        }
        List<MultipartFile> list = new ArrayList<>();
        for (MultipartFile file : files) {
            if (!file.isEmpty()) {
                list.add(file);
            }
        }
        FileUploadDto result = fileUploadService.batchUpload(list, category);
        return Result.success(result);
    }

    /**
     * 删除单个文件(逻辑删除+物理删除)
     * <p/>
     * update: 2025/12/07 00:22:50 修改返回类型
     *
     * @param fileId fileId
     * @return result.Result<cn.sichu.system.dto.FileDeleteDto>
     * @author sichu huang
     * @since 2025/11/30 06:30:58
     */
    @DeleteMapping("/delete/{fileId}")
    @Transactional(rollbackFor = Exception.class)
    public Result<FileDeleteDto> delete(@PathVariable("fileId") Long fileId) {
        FileUpload fileUpload = fileUploadService.getById(fileId);
        if (fileUpload == null || fileUpload.getIsDeleted() == TableLogic.DELETED.getCode()) {
            FileDeleteDto result = new FileDeleteDto();
            result.setLogicalSuccessCount(0);
            result.setPhysicalSuccessCount(0);
            result.setFailCount(1);
            result.setIncompleteOrFailedIds(List.of(fileId));
            return Result.success(result);
        }
        boolean physicalDeleted = FileUploadUtils.delete(fileUpload.getPath(), projectConfig);
        if (!physicalDeleted) {
            log.warn("物理删除失败: {}", fileUpload.getPath());
            String currentRemark = fileUpload.getRemark();
            String newRemark = (currentRemark != null ? currentRemark + "; " : "") + "物理删除失败: "
                + fileUpload.getPath();
            fileUpload.setRemark(newRemark);
            fileUpload.setUpdateBy(1L);
            fileUpload.setUpdateTime(LocalDateTime.now());
            fileUploadService.updateById(fileUpload);
        }
        LocalDateTime now = LocalDateTime.now();
        LambdaUpdateWrapper<FileUpload> query = new LambdaUpdateWrapper<>();
        query.eq(FileUpload::getId, fileId)
            .eq(FileUpload::getIsDeleted, TableLogic.NOT_DELETED.getCode())
            .set(FileUpload::getUpdateBy, 1L).set(FileUpload::getUpdateTime, now)
            .set(FileUpload::getDeleteBy, 1L).set(FileUpload::getDeleteTime, now)
            .set(FileUpload::getIsDeleted, TableLogic.DELETED.getCode());
        boolean logicalDeleted = fileUploadService.update(query);
        FileDeleteDto result = getFileDeleteDto(fileId, logicalDeleted, physicalDeleted);
        log.info("文件删除结果: fileId={}, 逻辑删除: {}, 物理删除: {}", fileId, logicalDeleted,
            physicalDeleted);
        return Result.success(result);
    }

    /**
     * 批量删除文件(逻辑删除+物理删除)
     * <p/>
     * update: 2025/12/06 23:43:55 修改返回类型
     *
     * @param fileIds fileIds
     * @return result.Result<java.util.Map < java.lang.String, java.lang.Object>>
     * @author sichu huang
     * @since 2025/11/30 06:54:52
     */
    @DeleteMapping("/batch-delete")
    @Transactional(rollbackFor = Exception.class)
    public Result<FileDeleteDto> batchDelete(@RequestBody List<Long> fileIds) {
        if (CollectionUtils.isEmpty(fileIds)) {
            throw new BusinessException(ResultCode.PARAMS_EMPTY);
        }
        int logicalSuccess = 0;
        int physicalSuccess = 0;
        List<Long> incompleteOrFailedIds = new ArrayList<>();
        for (Long fileId : fileIds) {
            try {
                FileUpload fileUpload = fileUploadService.getById(fileId);
                if (fileUpload == null
                    || fileUpload.getIsDeleted() == TableLogic.DELETED.getCode()) {
                    incompleteOrFailedIds.add(fileId);
                    continue;
                }
                boolean physicalDeleted =
                    FileUploadUtils.delete(fileUpload.getPath(), projectConfig);
                if (!physicalDeleted) {
                    log.warn("物理删除失败: {}, fileId: {}", fileUpload.getPath(), fileId);
                    fileUpload.setUpdateBy(1L);
                    LocalDateTime now = LocalDateTime.now();
                    fileUpload.setUpdateTime(now);
                    String timeStr = DateUtils.getMillionSecondStr(now);
                    String newRemark =
                        (fileUpload.getRemark() != null ? fileUpload.getRemark() + "; " : "")
                            + timeStr + "物理删除失败: " + fileUpload.getPath();
                    fileUpload.setRemark(newRemark);
                    fileUploadService.updateById(fileUpload);
                }
                LocalDateTime now = LocalDateTime.now();
                LambdaUpdateWrapper<FileUpload> query = new LambdaUpdateWrapper<>();
                query.eq(FileUpload::getId, fileId)
                    .eq(FileUpload::getIsDeleted, TableLogic.NOT_DELETED.getCode())
                    .set(FileUpload::getUpdateBy, 1L).set(FileUpload::getUpdateTime, now)
                    .set(FileUpload::getDeleteBy, 1L).set(FileUpload::getDeleteTime, now)
                    .set(FileUpload::getIsDeleted, TableLogic.DELETED.getCode());
                boolean logicalDeleted = fileUploadService.update(query);
                if (logicalDeleted) {
                    logicalSuccess++;
                    if (physicalDeleted) {
                        physicalSuccess++;
                    } else {
                        incompleteOrFailedIds.add(fileId);
                    }
                } else {
                    incompleteOrFailedIds.add(fileId);
                }
            } catch (Exception e) {
                log.error("删除文件异常: fileId={}", fileId, e);
                incompleteOrFailedIds.add(fileId);
            }
        }
        FileDeleteDto result = new FileDeleteDto();
        result.setLogicalSuccessCount(logicalSuccess);
        result.setPhysicalSuccessCount(physicalSuccess);
        result.setFailCount(incompleteOrFailedIds.size());
        result.setIncompleteOrFailedIds(incompleteOrFailedIds);
        return Result.success(result);
    }
}
