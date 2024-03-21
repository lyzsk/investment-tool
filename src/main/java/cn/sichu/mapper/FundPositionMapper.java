package cn.sichu.mapper;

import cn.sichu.entity.FundPosition;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
@Mapper
public interface FundPositionMapper {

    void insertFundPosition(FundPosition fundPosition);

    List<FundPosition> selectAllFundPosition();

    List<FundPosition> selectAllFundPositionByCode(String code);

    List<FundPosition> selectAllFundPositionByCodeOrderByTransactionDate(String code);

    List<FundPosition> selectFundPositionByCodeAndAfterTransactionDate(FundPosition fundPosition);

    List<FundPosition> selectFirstFundPositionByCode(String code);

    List<FundPosition> selectLastFunPositionByCode(String code);

    List<FundPosition> selectAllFundPositionByCodeExcludeFirstOne(String code);

    void updateHeldDaysAndUpdateDateForFundPosition(FundPosition fundPosition);

    void updateTotalAmountAndTotalPurchaseFeeAndHeldShareForFundPosition(FundPosition fundPosition);

}
