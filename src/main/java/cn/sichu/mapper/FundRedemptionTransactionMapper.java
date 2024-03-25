package cn.sichu.mapper;

import cn.sichu.entity.FundRedemptionTransaction;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
@Mapper
public interface FundRedemptionTransactionMapper {
    void insertFundRedemptionTransaction(FundRedemptionTransaction fundRedemptionTransaction);

    List<FundRedemptionTransaction> selectAllFundRedemptionTransactionByStatus(Integer status);

    List<FundRedemptionTransaction> selectAllFundRedemptionTransactionWithNullNavAndAmount();

    void updateStatus(FundRedemptionTransaction fundRedemptionTransaction);

    void updateNavAndAmount(FundRedemptionTransaction fundRedemptionTransaction);
}
