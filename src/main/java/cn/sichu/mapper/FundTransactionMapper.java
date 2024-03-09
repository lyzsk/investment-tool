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

    public List<FundTransaction> selectAllFundTransaction();

    public void insertFundTransaction(FundTransaction fundTransaction);
}
