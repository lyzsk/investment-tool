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

    /**
     * 按 bvid 计数, 含已逻辑删除的行(发现去重用: 用户删掉的误捞旧稿不能被发现任务当新稿重新插入)
     *
     * @author sichu huang
     * @param bvid bvid
     * @since 2026/10/12
     * @return long
     **/
    long countAnyByBvid(@Param("bvid") String bvid);

    /**
     * 取待处理: step 匹配且未超重试上限; origin 非空时只取该来源(DAILY/BACKFILL, 10/12 加, 补跑行不进每日队列)
     *
     * @author sichu huang
     * @param step step
     * @param maxRetry maxRetry
     * @param origin origin
     * @since 2026/10/12
     * @return java.util.List<cn.sichu.bilibili.entity.BilibiliVideo>
     **/
    List<BilibiliVideo> selectByStep(@Param("step") String step, @Param("maxRetry") int maxRetry,
        @Param("origin") String origin);
}
