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

    List<FundPosition> selectAllFundPositionWithNullMark(String code);

    List<FundPosition> selectFundPositionWithMaxHeldShareByCode(String code);

    List<FundPosition> selectFundPositionByCodeAndAfterTransactionDate(FundPosition fundPosition);

    List<FundPosition> selectLastFundPosition(FundPosition fundPosition);

    List<FundPosition> selectAllFundPositionByConditionsOrderByTransactionDate(@Param("code") String code, @Param("heldDays") Integer heldDays,
        @Param("endDate") Date endDate);

    void updateTotalAmountAndHeldDaysAndUpdateDate(FundPosition fundPosition);

    void updateTotalPrincipalAmountAndTotalPurchaseFeeAndHeldShareAndTotalAmount(FundPosition fundPosition);

}
