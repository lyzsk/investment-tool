package cn.sichu.mapper;

import cn.sichu.entity.FundPosition;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
@Mapper
public interface FundPositionMapper {

    void insertFundPosition(FundPosition fundPosition);

    void deleteFundPosition(Long id);

    List<FundPosition> selectAllFundPosition();

    List<FundPosition> selectAllFundPositionByCodeOrderByTransactionDate(String code);

    List<FundPosition> selectFundPositionByCodeAndAfterTransactionDate(FundPosition fundPosition);

    List<FundPosition> selectLastFundPositionInDifferentDate(FundPosition fundPosition);

    List<FundPosition> selectLastFundPositionInSameDate(FundPosition fundPosition);

    List<FundPosition> selectAllFundPositionByConditions(@Param("code") String code, @Param("startDate") Date startDate,
        @Param("endDate") Date endDate);

    void updateHeldDaysAndUpdateDate(FundPosition fundPosition);

    void updateTotalAmountAndTotalPurchaseFeeAndHeldShare(FundPosition fundPosition);

}
