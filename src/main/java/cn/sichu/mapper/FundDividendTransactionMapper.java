package cn.sichu.mapper;

import cn.sichu.entity.FundDividendTransaction;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @date 2024/04/07
 **/
@Mapper
public interface FundDividendTransactionMapper {

    void insertFundDividendTransaction(FundDividendTransaction fundDividendTransaction);
}
