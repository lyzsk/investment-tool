package cn.sichu.mapper;

import cn.sichu.entity.FundPurchaseTransaction;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
@Mapper
public interface FundPurchaseTransactionMapper {

    public void insertFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction);
}
