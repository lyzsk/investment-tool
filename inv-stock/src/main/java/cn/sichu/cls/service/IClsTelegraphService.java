package cn.sichu.cls.service;

import cn.sichu.cls.entity.ClsTelegraph;
import com.baomidou.mybatisplus.extension.service.IService;

import java.time.LocalDate;

/**
 * @author sichu huang
 * @since 2026/01/03 16:18
 */
public interface IClsTelegraphService extends IService<ClsTelegraph> {

    // /**
    //  * 拉取<a href="https://www.cls.cn/nodeapi/updateTelegraphList">电报json</a>中最新的电报
    //  *
    //  * @return int 拉取的电报条数
    //  * @author sichu huang
    //  * @since 2026/01/03 16:56:25
    //  */
    // int fetchAndSaveLatestTelegraphs();

    /**
     * 拉取并保存所有 level="B" 的电报(加红电报)
     *
     * @return int
     * @author sichu huang
     * @since 2026/01/14 13:47:13
     */
    int fetchAndSaveAllRedTelegraphs();

    /**
     * 拉取<a href="https://www.cls.cn/nodeapi/updateTelegraphList">电报json</a>中的 "收评" 电报
     * <p/>
     * 保存至`cls_telegraph`
     * <p/>
     * 下载第一张图片(包含重命名)到`downloads/cls/yyyy.mm.dd/`目录下
     *
     * @return int  拉取的电报条数
     * @author sichu huang
     * @since 2026/01/08 16:13:12
     */
    int fetchAndSaveShouPingTelegraphs();

    /**
     * 拉取<a href="https://www.cls.cn/nodeapi/updateTelegraphList">电报json</a>中的 "M月M日涨停分析" 电报
     * <p/>
     * 保存至`cls_telegraph`
     * <p/>
     * 下载第一张图片(包含重命名)到`downloads/cls/yyyy.mm.dd/`目录下
     *
     * @return int 拉取的电报条数
     * @author sichu huang
     * @since 2026/01/08 16:13:18
     */
    int fetchAndSaveZhangTingTelegraphs();

    /**
     * 为“下一个交易日”生成或更新 Markdown 日记文件。
     * <p>
     * - 计算 nextTradingDay = getNextTradingDay(today)
     * - 若 nextTradingDay 是交易日（必然成立），则：
     * 1. 创建 stock/{next}.md（若不存在）
     * 2. 初始化模板（若首次创建）
     * 3. 从上一交易日继承“复盘持仓”中的 #### 标题行到“当前持仓”
     *
     * @param today 当前日期(LocalDate.now())
     * @return boolean
     * @author sichu huang
     * @since 2026/01/13 16:56:09
     */
    boolean generateMarkdown(LocalDate today);

    /**
     * 将指定日期所有 level="B" 的电报（含图片）追加/覆盖到该日 Markdown 文件的 "## 加红电报" 区块
     *
     * @param date 当前日期(LocalDate.now())
     * @return boolean
     * @author sichu huang
     * @since 2026/01/14 12:50:35
     */
    boolean appendRedTelegraphs(LocalDate date);
}
