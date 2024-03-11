package cn.sichu.mapper;

import cn.sichu.entity.FundHistoryNav;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @date 2024/03/11
 **/
@Mapper
public interface FundHistoryNavMapper {
    public void insertFundHistoryNavInformation(FundHistoryNav fundHistoryNav);
}
