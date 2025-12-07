package cn.sichu.system.file.dto;

import cn.sichu.system.file.entity.FileUpload;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * @author sichu huang
 * @since 2025/12/06 23:28
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class FileUploadDto {
    private List<FileUpload> successList;
    private int successCount;
    private int failCount;
    private List<String> failFilenames;
}
