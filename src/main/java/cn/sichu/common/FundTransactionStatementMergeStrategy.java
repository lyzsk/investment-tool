package cn.sichu.common;

import com.alibaba.excel.metadata.Head;
import com.alibaba.excel.write.merge.AbstractMergeStrategy;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.Sheet;

/**
 * FundTransactionStatement 工作簿单元格合并策略
 *
 * @author sichu huang
 * @date 2024/04/01
 **/
public class FundTransactionStatementMergeStrategy extends AbstractMergeStrategy {

    /* 目标合并列index */
    private Integer targetColumnIndex;

    /* 需要开始合并单元格的首行index */
    private Integer startRowIndex;

    /* 需要开始合并单元格的末行index */
    private Integer endRowIndex;

    @Override
    protected void merge(Sheet sheet, Cell cell, Head head, Integer relativeRowIndex) {

    }
}
