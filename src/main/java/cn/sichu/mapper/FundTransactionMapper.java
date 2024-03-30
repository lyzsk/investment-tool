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

    List<FundTransaction> selectAllFundTransaction();

    List<FundTransaction> selectAllFundTransactionInTransit();

    List<FundTransaction> selectAllFundTransactionWithNullNavAndShareForPurchaseType();

    List<FundTransaction> selectAllFundTransactionWithNullNavAndFeeAndAmountForRedemptionType();

    void updateStatus(FundTransaction fundTransaction);

    void updateNavAndShare(FundTransaction fundTransaction);

    void updateNavAndFeeAndAmount(FundTransaction fundTransaction);
}
