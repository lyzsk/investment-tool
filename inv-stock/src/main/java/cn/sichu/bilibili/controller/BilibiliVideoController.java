package cn.sichu.bilibili.controller;

import cn.sichu.bilibili.entity.BilibiliVideo;
import cn.sichu.bilibili.service.IBilibiliVideoService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import result.Result;

import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/09/27 13:08
 */
@RestController
@RequestMapping("/api/bilibili/video")
@RequiredArgsConstructor
public class BilibiliVideoController {
    private final IBilibiliVideoService bilibiliVideoService;

    /**
     * 推进 VISION_DONE → SUMMARIZED(30 天物理删除倒计时由此起算)
     *
     * @param bvids bvid 列表
     * @return result.Result<java.lang.String> "推进SUMMARIZED x/跳过 y(非VISION_DONE)/未找到 z"
     * @author sichu huang
     * @since 2026/09/27 13:09:24
     */
    @PostMapping("/markSummarized")
    public Result<String> markSummarized(@RequestBody List<String> bvids) {
        return Result.success(bilibiliVideoService.markSummarized(bvids));
    }

    /**
     * /taoge-sum skill 发现入口: 返回待合成的 VISION_DONE 列表(retry_count<3)
     * 例: curl localhost:8888/api/bilibili/video/pendingSummary
     *
     * @return result.Result<java.util.List<cn.sichu.bilibili.entity.BilibiliVideo>>
     * @author sichu huang
     * @since 2026/09/27
     */
    @GetMapping("/pendingSummary")
    public Result<List<BilibiliVideo>> pendingSummary() {
        return Result.success(bilibiliVideoService.listByStep("VISION_DONE", 3));
    }
}
