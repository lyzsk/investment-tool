package cn.sichu.cls.service;

import cn.sichu.cls.entity.ClsTelegraph;
import com.baomidou.mybatisplus.extension.service.IService;

import java.time.LocalDate;

/**
 * @author sichu huang
 * @since 2026/01/03 16:18
 */
public interface IClsTelegraphService extends IService<ClsTelegraph> {

    /**
     * 拉取并保存所有 level="B" 的电报(加红电报, OCR 自动填充 午评, 收评, 午间涨停分析, 涨停分析)
     *
     * @return int
     * @author sichu huang
     * @since 2026/01/14 13:47:13
     */
    int fetchAndSaveAllRedTelegraphs();

    /**
     * 为“下一个交易日”生成或更新 Markdown 日记文件。
     * <p>
     * - 计算 nextTradingDay = getNextTradingDay(today)
     * - 若 nextTradingDay 是交易日（必然成立），则：
     * 1. 创建 stock/{next}.md（若不存在）
     * 2. 初始化模板（若首次创建）
     * 3. 从上一交易日继承“复盘持仓”中的 #### 标题行到“当前持仓”
     *
     * @param today LocalDate
     * @return boolean
     * @author sichu huang
     * @since 2026/01/13 16:56:09
     */
    boolean generateMarkdown(LocalDate today);

    /**
     * 将指定日期所有 level="B" 的电报（含图片）追加/覆盖到该日 Markdown 文件的 "## 加红电报" 区块
     *
     * @param date LocalDate
     * @return boolean
     * @author sichu huang
     * @since 2026/01/14 12:50:35
     */
    boolean appendRedTelegraphs(LocalDate date);

    /**
     * 物理删除 downloads/cls/<yyyy.MM.dd>/ 下超过 retentionDays 天的日期目录(按目录名日期判定)
     * DB cls_telegraph.images 存的是远程 URL, 删本地文件不动表
     *
     * @param retentionDays 保留天数
     * @return java.lang.String "cls图片清理 x 个日期目录/失败 y"
     * @author sichu huang
     * @since 2026/09/27 12:26:27
     */
    String cleanupLocalImages(int retentionDays);
}
