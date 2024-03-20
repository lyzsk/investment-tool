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

    List<FundPosition> selectAllFundPositionByCode(String code);

    void insertFundPosition(FundPosition fundPosition);

    void updateHeldDaysAndUpdateDateForFundPosition(FundPosition fundPosition);

    List<FundPosition> selectLastFunPositionByCode(String code);

    List<FundPosition> selectallFundPosition();
}
