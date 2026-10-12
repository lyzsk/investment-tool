package cn.sichu.paper.service;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
public interface IChainIngestService {

    /**
     * 解析一次链运行目录 results/&lt;skill&gt;_chain/{live|asof}-yyyyMMdd/ 写 chain_run/chain_step/chain_decision/chain_decision_rule
     * 同 (skill, mode, runDate, slot) 先物理删除再插入(幂等); 文件仍是唯一事实, DB 只是索引
     *
     * @author sichu huang
     * @param skill skill
     * @param mode LIVE / ASOF
     * @param runDate runDate
     * @param slot HHMM / review / FINAL
     * @param exitCode driver 退出码, 历史补导传 null
     * @param startedAt 进程开始, 历史补导传 null
     * @param finishedAt 进程结束, 历史补导传 null(取目录最新 mtime)
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String ingest(String skill, String mode, LocalDate runDate, String slot, Integer exitCode, LocalDateTime startedAt,
        LocalDateTime finishedAt) throws Exception;

    /**
     * 历史补导: 扫 results/*_chain/ 下全部 live-/asof- 目录(跳过 .interrupted 等改名目录), 按目录最终状态入库 slot=FINAL;
     * 已有实盘时段行(handler 实时入库过)的 (skill, mode, 日) 不再补 FINAL, 防重复
     *
     * @author sichu huang
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String ingestAll() throws Exception;
}
