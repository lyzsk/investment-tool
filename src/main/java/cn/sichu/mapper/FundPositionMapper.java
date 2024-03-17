package cn.sichu.mapper;

import cn.sichu.entity.FundPosition;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
@Mapper
public interface FundPositionMapper {

    public void insertFundPosition(FundPosition fundPosition);
}
