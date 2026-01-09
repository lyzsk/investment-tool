package cn.sichu.cls.service;

import cn.sichu.cls.entity.ClsTelegraph;
import com.baomidou.mybatisplus.extension.service.IService;

/**
 * @author sichu huang
 * @since 2026/01/03 16:18
 */
public interface IClsTelegraphService extends IService<ClsTelegraph> {

    /**
     * 拉取<a href="https://www.cls.cn/nodeapi/updateTelegraphList">电报json</a>中最新的电报
     *
     * @return int 拉取的电报条数
     * @author sichu huang
     * @since 2026/01/03 16:56:25
     */
    int fetchAndSaveLatestTelegraphs();

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
}
