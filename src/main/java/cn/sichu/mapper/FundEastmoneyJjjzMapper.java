package cn.sichu.mapper;

import cn.sichu.entity.FundEastmoneyJjjz;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/18
 **/
@Mapper
public interface FundEastmoneyJjjzMapper {

    public List<FundEastmoneyJjjz> selectCallbackByCode(String code);
}
