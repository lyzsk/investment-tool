package cn.sichu.mapper;

import cn.sichu.entity.GoldPosition;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

/**
 * @author sichu huang
 * @date 2024/06/10
 **/
@Mapper
public interface GoldPositionMapper {
    void insertGoldPosition(GoldPosition position);

    List<GoldPosition> selectGoldPositionWithNullMark();

    List<GoldPosition> selectGoldPositionAfterDateTime(GoldPosition goldPosition);

    List<GoldPosition> selectLastGoldPosition(GoldPosition goldPosition);

    void updateGoldPositionWhenPurchase(GoldPosition goldPosition);

    void updateGoldPositionWhenRedeem(GoldPosition position);

    void updateHeldDays(GoldPosition position);
}
