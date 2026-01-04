package cn.sichu.cls.service;

import cn.sichu.cls.entity.ClsTelegraph;
import com.baomidou.mybatisplus.extension.service.IService;
import com.fasterxml.jackson.databind.JsonNode;

/**
 * @author sichu huang
 * @since 2026/01/03 16:18
 */
public interface IClsTelegraphService extends IService<ClsTelegraph> {

    /**
     * 根据财联社原始ID查询电报
     *
     * @param clsId clsId
     * @return cn.sichu.cls.entity.ClsTelegraph
     * @author sichu huang
     * @since 2026/01/03 16:19:06
     */

    ClsTelegraph getByClsId(Long clsId);

    /**
     * 保存或更新电报(自动去重)
     *
     * @param itemNode JsonNode
     * @return boolean
     * @author sichu huang
     * @since 2026/01/03 16:19:28
     */
    boolean saveOrUpdateFromRaw(JsonNode itemNode);

    /**
     * @author sichu huang
     * @since 2026/01/03 16:56:25
     */
    void fetchAndSaveLatestTelegraphs();
}
