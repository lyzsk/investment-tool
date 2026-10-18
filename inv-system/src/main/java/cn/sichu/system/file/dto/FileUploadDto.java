package cn.sichu.system.file.dto;

import cn.sichu.system.file.entity.FileUpload;

import java.util.List;

/**
 * @author sichu huang
 * @since 2025/12/06 23:28
 */
public record FileUploadDto(List<FileUpload> successList, int successCount, int failCount,
                            List<String> failFilenames, List<String> skippedFilenames) {
}
