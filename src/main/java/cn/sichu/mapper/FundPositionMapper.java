package cn.sichu.mapper;

import cn.sichu.entity.FundPosition;
import cn.sichu.entity.FundTransaction;
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

    List<FundPosition> selectAllFundPositionByStatus(@Param("status") Integer status);

    List<FundPosition> selectAllFundPositionWithNullMark();

    List<FundPosition> selectAllFundPositionWithNullMarkAndNotNullTotalAmount();

    List<FundPosition> selectAllFundPositionWithNullMarkByCode(String code);

    List<FundPosition> selectFundPositionWithMaxHeldShareByConditions(@Param("code") String code, @Param("type") Integer type);

    List<FundPosition> selectFundPositionByCodeAndAfterTransactionDate(FundPosition fundPosition);

    List<FundPosition> selectLastFundPosition(FundPosition fundPosition);

    List<FundPosition> selectAllFundPositionByConditionsOrderByTransactionDate(@Param("code") String code, @Param("heldDays") Integer heldDays,
        @Param("endDate") Date endDate);

    List<FundPosition> selectFundPositionByPurchaseTransaction(FundTransaction transaction);

    List<FundPosition> selectAllFundPositionWithNullTotalAmountAndTotalRedemptionFee();

    void updateStatus(FundPosition fundPosition);

    void updateHeldDaysAndUpdateDate(FundPosition fundPosition);

    void updateTotalPrincipalAmountAndTotalPurchaseFeeAndHeldShareAndTotalAmount(FundPosition fundPosition);

    void updateWhenRedeemFund(FundPosition fundPosition);

    void updateRemainingFundPosition(FundPosition fundPosition);

    void updateTotalAmount(FundPosition fundPosition);

    void updateTotalRedemptionFeeAndTotalAmount(FundPosition fundPosition);
}
