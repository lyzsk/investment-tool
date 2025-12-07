package cn.sichu.system.file.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * @author sichu huang
 * @since 2025/12/06 23:41
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class FileDeleteDto {
    private int logicalSuccessCount;
    private int physicalSuccessCount;
    /**
     * 失败的数量（包括：文件不存在、逻辑删除失败、异常等）
     */
    private int failCount;
    /**
     * 所有未能完成完整删除（逻辑+物理）的文件 ID
     * 包括:
     * - 文件不存在
     * - 逻辑删除失败
     * - 物理删除失败
     */
    private List<Long> incompleteOrFailedIds;
}
