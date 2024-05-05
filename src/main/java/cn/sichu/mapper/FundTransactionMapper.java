package cn.sichu.mapper;

import cn.sichu.entity.FundTransaction;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Mapper
public interface FundTransactionMapper {

    void insertFundTransaction(FundTransaction fundTransaction);

    List<FundTransaction> selectAllCode();

    List<FundTransaction> selectAllHeldCode();

    List<FundTransaction> selectAllFundTransactionInTransit(@Param("status1") Integer status1, @Param("status2") Integer status2);

    List<FundTransaction> selectAllPurchaseTransactionWithNullNavAndShare(@Param("type") Integer type);

    List<FundTransaction> selectAllRedemptionFundTransactionWithNullAmountAndFeeAndNav(@Param("code") String code,
        @Param("redemptionDate") Date redemptionDate, @Param("type") Integer type);

    void updateStatus(FundTransaction fundTransaction);

    void updateNavAndShare(FundTransaction fundTransaction);

    void updateNavAndFeeAndAmount(FundTransaction fundTransaction);

    void updateMarkByConditions(@Param("code") String code, @Param("mark") String mark, @Param("startDate") Date startDate,
        @Param("endDate") Date endDate);

}
