package cn.sichu.mapper;

import cn.sichu.entity.FundHistoryPosition;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @date 2024/03/17
 **/
@Mapper
public interface FundHistoryPositionMapper {

    void insertFundHistoryPosition(FundHistoryPosition fundHistoryPosition);
}
