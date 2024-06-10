package cn.sichu.mapper;

import cn.sichu.entity.GoldTransaction;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @date 2024/06/10
 **/
@Mapper
public interface GoldTransactionMapper {
    void insertGoldTransaction(GoldTransaction transaction);
}
