package cn.sichu.mapper;

import cn.sichu.entity.GoldPosition;
import cn.sichu.entity.GoldTransaction;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/06/11
 **/
@Mapper
public interface GoldTransactionSummarySheetMapper {
    List<GoldTransaction> selectAllGoldTransaction();

    List<GoldPosition> selectAllGoldPosition();
}
