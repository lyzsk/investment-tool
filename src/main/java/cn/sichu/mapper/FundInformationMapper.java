package cn.sichu.mapper;

import cn.sichu.entity.FundInformation;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Mapper
public interface FundInformationMapper {

    public List<FundInformation> selectFundShortNameByCode(String code);

    public List<FundInformation> selectFundTransactionProcessByCode(String code);

}
