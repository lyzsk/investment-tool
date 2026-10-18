package cn.sichu.reconcile.service;

import cn.sichu.reconcile.entity.ReconcileResult;
import com.baomidou.mybatisplus.extension.service.IService;

import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
public interface IReconcileResultService extends IService<ReconcileResult> {

    /**
     * 新批次号: yyyyMMddHHmmss_业务
     *
     * @author sichu huang
     * @param bizType bizType
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String newBatchNo(String bizType);

    /**
     * 构造一行(不落库), detail 超长截断到 1000
     *
     * @author sichu huang
     * @param batchNo batchNo
     * @param bizType bizType
     * @param bizKey bizKey
     * @param checkItem checkItem
     * @param expected expected
     * @param actual actual
     * @param result result
     * @param detail detail
     * @since 2026/10/12
     * @return cn.sichu.reconcile.entity.ReconcileResult
     **/
    ReconcileResult of(String batchNo, String bizType, String bizKey, String checkItem, Object expected,
        Object actual, String result, String detail);

    /**
     * 批量落库, 并把非 OK 行汇总成一条消息推 hermes(全 OK 不推); 返回汇总文字
     *
     * @author sichu huang
     * @param title 消息标题
     * @param rows rows
     * @since 2026/10/12
     * @return java.lang.String
     **/
    String saveAndNotify(String title, List<ReconcileResult> rows);
}
