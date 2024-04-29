package cn.sichu.mapper;

import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundPosition;
import cn.sichu.entity.FundTransaction;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/04/29
 **/
@Mapper
public interface FundTransactionReportSheetMapper {
    List<FundPosition> selectAllFundPositionByConditions();

    List<FundInformation> selectFundInformationByCode(String code);

    List<FundTransaction> selectAllDividendTransactionByConditions(@Param("startDate") Date startDate, @Param("endDate") Date endDate,
        @Param("type") Integer type);
}
