package cn.sichu.system.file.dto;

import java.util.List;

/**
 * failCount
 * 失败的数量（包括：文件不存在、逻辑删除失败、异常等）
 * <p/>
 * List<Long> incompleteOrFailedIds
 * 所有未能完成完整删除（逻辑+物理）的文件 ID
 * 包括:
 * - 文件不存在
 * - 逻辑删除失败
 * - 物理删除失败
 *
 * @author sichu huang
 * @since 2025/12/06 23:41
 */
public record FileDeleteDto(int logicalSuccessCount, int physicalSuccessCount, int failCount,
                            List<Long> incompleteOrFailedIds) {

}
