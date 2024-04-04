package cn.sichu.mapper;

import cn.sichu.entity.FundPurchaseTransaction;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;
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

    void updateStatus(FundPurchaseTransaction fundPurchaseTransaction);

    void updateNavAndShare(FundPurchaseTransaction fundPurchaseTransaction);

    void updateMarkByConditions(@Param("code") String code, @Param("mark") String mark, @Param("startDate") Date startDate,
        @Param("endDate") Date endDate);
}
