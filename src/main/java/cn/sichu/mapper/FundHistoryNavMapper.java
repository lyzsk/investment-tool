package cn.sichu.mapper;

import cn.sichu.entity.FundHistoryNav;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/11
 **/
@Mapper
public interface FundHistoryNavMapper {

    void insertFundHistoryNav(FundHistoryNav fundHistoryNav);

    List<FundHistoryNav> selectFundHistoryNavByConditions(@Param("code") String code, @Param("navDate") Date navDate);

    List<FundHistoryNav> selectLastHistoryNav(@Param("code") String code);
}
