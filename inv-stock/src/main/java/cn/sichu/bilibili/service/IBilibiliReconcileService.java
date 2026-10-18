package cn.sichu.bilibili.service;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
public interface IBilibiliReconcileService {

    /**
     * UP 主视频管线对账(§5.4, 用户 10/11 立法: sum+distill 天数必须与 results/ 对得上):
     * 逐 UP 逐视频核 results 产物是否齐(txt + vision.json 有 pages/vlm) → md 里有没有它的 bvid(=已 sum) → 所在 md 日是否在 distill 账本(=已蒸馏);
     * 同时把 bilibili_video 同步到文件事实: 缺行补登记(origin=BACKFILL), step 落后就推进(VISION_DONE→SUMMARIZED→DISTILLED), 不回退;
     * 结果写 reconcile_result, 有缺口推 hermes
     *
     * @author sichu huang
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String reconcile() throws Exception;

    /**
     * 补跑登记: 从 scripts/backfill_bilibili/ 的 UP 视频索引里取 [from, to] 内、库里没有且产物未齐的视频, 插 NEW 行(origin=BACKFILL), 最多 max 条;
     * 之后由 bilibiliBackfillHandler 限量下载+处理, sum/distill 仍走 backfill_bilibili.py --llm-batch(按天), 对账再把 DB 推进
     *
     * @author sichu huang
     * @param up ups.json 的键: taoge / qushitiange / lubenyuan
     * @param from from, 可空
     * @param to to, 可空
     * @param max max
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String enqueueBackfill(String up, LocalDate from, LocalDate to, int max) throws Exception;

    /**
     * ups.json 里 UP 键 → mid
     *
     * @author sichu huang
     * @param up up
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String midOf(String up) throws Exception;
}
