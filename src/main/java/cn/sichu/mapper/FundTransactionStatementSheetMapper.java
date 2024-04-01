package cn.sichu.mapper;

import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundTransaction;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/04/01
 **/
@Mapper
public interface FundTransactionStatementSheetMapper {
    List<FundTransaction> selectAllFundTransaction();

    List<FundInformation> selectFundInformationByCode(String code);
}
