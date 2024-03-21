package cn.sichu.mapper;

import cn.sichu.entity.FundTransaction;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Mapper
public interface FundTransactionMapper {

    void insertFundTransaction(FundTransaction fundTransaction);

    List<FundTransaction> selectAllFundTransactions();

    List<FundTransaction> selectAllFundTransactionsInTransit();

    List<FundTransaction> selectAllFundTransactionWithNullNavAndShare();

    void updateStatusForFundTransaction(FundTransaction fundTransaction);

    void updateNavAndShareForFundTransaction(FundTransaction fundTransaction);

}
