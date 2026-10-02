package cn.sichu.tzzb.service;

import cn.sichu.tzzb.entity.TzzbRecord;
import com.baomidou.mybatisplus.extension.service.IService;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/01 23:44
 */
public interface ITzzbRecordService extends IService<TzzbRecord> {

    /**
     * 读 downloads/tzzb/<ledger>/*.json 解析入库
     *
     * @param ledger 账本标识(scripts/tzzb_ledgers.json 里的 ledger
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/10/01 23:46:05
     */
    String syncFromRawJson(String ledger);

    /**
     * 某账本某交易日净值是否已入库
     *
     * @param ledger 账本标识
     * @param day    yyyy-MM-dd
     * @return boolean
     * @author sichu huang
     * @since 2026/10/01 23:46:59
     */
    boolean hasNavDay(String ledger, LocalDate day);
}
