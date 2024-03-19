package cn.sichu.mapper;

import cn.sichu.entity.FundPurchaseTransaction;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
@Mapper
public interface FundPurchaseTransactionMapper {

    public List<FundPurchaseTransaction> selectAllFundPurchaseTransactions();

    public void insertFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);

    public void updateNavAndShareForFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);

    public void updateStatusForFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);

    List<FundPurchaseTransaction> selectAllFundPurchaseTransactionsByConditions(String code, Integer status);

    List<FundPurchaseTransaction> selectAllFundPurchaseTransactionsByStatus(Integer status);
}
