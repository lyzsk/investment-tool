package cn.sichu.system.file.mapper;

import cn.sichu.system.file.entity.FileUpload;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * @author sichu huang
 * @since 2025/11/30 05:41
 */
@Mapper
public interface FileUploadMapper extends BaseMapper<FileUpload> {

    List<FileUpload> selectByCategoryAndNotDeleted(@Param("category") String category);
}
