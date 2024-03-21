package cn.sichu.mapper;

import cn.sichu.entity.FundHistoryNav;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/11
 **/
@Mapper
public interface FundHistoryNavMapper {
    void insertFundHistoryNav(FundHistoryNav fundHistoryNav);

    List<FundHistoryNav> selectFundHistoryNavByConditions(FundHistoryNav fundHistoryNav);

    List<FundHistoryNav> selectLastFundHistoryNavDateByConditions(FundHistoryNav fundHistoryNav);

    List<FundHistoryNav> selectLastFundHistoryNavDates();
}
