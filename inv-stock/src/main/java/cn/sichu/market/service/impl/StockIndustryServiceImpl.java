package cn.sichu.market.service.impl;

import cn.sichu.market.entity.StockIndustry;
import cn.sichu.market.mapper.StockIndustryMapper;
import cn.sichu.market.service.IStockIndustryService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import utils.CollectionUtils;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 个股行业时点查询: 申万(SW)优先, 申万当日无归属退证监会(CSRC)
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
@Service
@RequiredArgsConstructor
public class StockIndustryServiceImpl implements IStockIndustryService {
    /* 口径优先级: 申万在前 */
    private static final String SW = "SW";
    /* IN 列表每批个数 */
    private static final int BATCH_SIZE = 500;

    private final StockIndustryMapper stockIndustryMapper;

    @Override
    public StockIndustry getIndustry(String symbol, LocalDate date) {
        return mapIndustry(List.of(symbol), date).get(symbol);
    }

    @Override
    public Map<String, StockIndustry> mapIndustry(Collection<String> symbols, LocalDate date) {
        Map<String, StockIndustry> result = new HashMap<>();
        if (CollectionUtils.isEmpty(symbols)) {
            return result;
        }
        for (List<String> part : CollectionUtils.partition(new ArrayList<>(symbols), BATCH_SIZE)) {
            List<StockIndustry> rows = stockIndustryMapper.selectList(
                new LambdaQueryWrapper<StockIndustry>().in(StockIndustry::getSymbol, part)
                    .le(StockIndustry::getInDate, date)
                    .and(w -> w.isNull(StockIndustry::getOutDate).or().gt(StockIndustry::getOutDate, date)));
            for (StockIndustry row : rows) {
                StockIndustry old = result.get(row.getSymbol());
                if (old == null || (!SW.equals(old.getClassification()) && SW.equals(row.getClassification()))) {
                    result.put(row.getSymbol(), row);
                }
            }
        }
        return result;
    }
}
