package cn.sichu.cls.mapper;

import cn.sichu.cls.entity.ClsTelegraph;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.time.LocalDateTime;
import java.util.List;

/**
 * @author sichu huang
 * @since 2026/01/03 16:17
 */
@Mapper
public interface ClsTelegraphMapper extends BaseMapper<ClsTelegraph> {
    List<ClsTelegraph> selectRedTelegraphs(@Param("level") String level,
        @Param("start") LocalDateTime start, @Param("end") LocalDateTime end);
}
