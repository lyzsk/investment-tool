package cn.sichu.bilibili.service;

import cn.sichu.bilibili.entity.BilibiliVideo;
import com.baomidou.mybatisplus.extension.service.IService;

import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/09/26 21:24
 */
public interface IBilibiliVideoService extends IService<BilibiliVideo> {

    /**
     * 按 bvid 查重
     *
     * @param bvid B站BV号
     * @return cn.sichu.bilibili.entity.BilibiliVideo
     * @author sichu huang
     * @since 2026/09/26 21:25:03
     */
    BilibiliVideo getByBvid(String bvid);

    /**
     * 下一阶段 job 取待处理列表: step 匹配且未超重试上限的行
     *
     * @param step     step
     * @param maxRetry maxRetry
     * @return java.util.List<cn.sichu.bilibili.entity.BilibiliVideo>
     * @author sichu huang
     * @since 2026/09/26 21:26:03
     */
    List<BilibiliVideo> listByStep(String step, int maxRetry);

    /**
     * 下载所有 step=NEW 且未超重试上限的视频(mp4+m4a+json) → DOWNLOADED
     *
     * @param maxRetry 重试上限
     * @param authorMid UP 隔离(10/7 晚二修): 只处理该 mid 的行, 防跨 UP 认领被归属闸拒绝空烧 retry
     * @return java.lang.String "下载成功 x/失败 y"
     * @author sichu huang
     * @since 2026/09/27 01:01:35
     */
    String downloadPendingVideos(int maxRetry, String authorMid);

    /**
     * 处理所有 step=DOWNLOADED 且未超重试上限的视频: 直链 process_video.py(ASR→纠错→视觉→聚合),
     * 产物到 results/bilibili/<作者mid>/<发布日>/ → VISION_DONE
     *
     * @param maxRetry 重试上限
     * @param authorMid UP 隔离(同上)
     * @return java.lang.String "处理成功 x/失败 y"
     * @author sichu huang
     * @since 2026/09/27 13:10:38
     */
    String processPendingVideos(int maxRetry, String authorMid);

    /**
     * 物理删除 SUMMARIZED 且超过 retentionDays 天的视频原料(mp4+m4a+json 三件套,
     * 路径按命名约定从 bvid/author_mid/publish_time 派生), remark 记删除时间,
     * DB 行保留(防重复下载)
     *
     * @param retentionDays 保留天数
     * @return java.lang.String "bilibili原料清理 x/失败 y"
     * @author sichu huang
     * @since 2026/09/27 13:11:04
     */
    String cleanupPhysicalFiles(int retentionDays);

    /**
     * VISION_DONE → SUMMARIZED(30 天物理删除倒计时从本推进的 update_time 起算)
     * 只推进 step=VISION_DONE 的行(防把没跑完视觉的误标), 其他状态跳过计数
     *
     * @param bvids bvid 列表
     * @return java.lang.String "推进SUMMARIZED x/跳过 y(非VISION_DONE)/未找到 z"
     * @author sichu huang
     * @since 2026/09/27 13:11:23
     */
    String markSummarized(List<String> bvids);
}
