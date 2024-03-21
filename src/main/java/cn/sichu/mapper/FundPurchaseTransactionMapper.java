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

    void insertFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);

    List<FundPurchaseTransaction> selectAllFundPurchaseTransactionsByStatus(Integer status);

    List<FundPurchaseTransaction> selectAllFundPuchaseTransactionWithNullNavAndShare();

    void updateStatusForFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);

    void updateNavAndShareForFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);

}
