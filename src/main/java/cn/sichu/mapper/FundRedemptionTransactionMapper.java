package cn.sichu.mapper;

import cn.sichu.entity.FundRedemptionTransaction;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
@Mapper
public interface FundRedemptionTransactionMapper {
    void insertFundRedemptionTransaction(FundRedemptionTransaction fundRedemptionTransaction);
}
