package cn.sichu.bilibili.mapper;

import cn.sichu.bilibili.entity.BilibiliVideo;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/09/26 21:06
 */
@Mapper
public interface BilibiliVideoMapper extends BaseMapper<BilibiliVideo> {

    List<BilibiliVideo> selectByStep(@Param("step") String step, @Param("maxRetry") int maxRetry);
}
