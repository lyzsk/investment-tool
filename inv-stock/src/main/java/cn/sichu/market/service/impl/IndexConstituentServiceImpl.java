package cn.sichu.market.service.impl;

import cn.sichu.market.entity.IndexConstituent;
import cn.sichu.market.entity.IndexConstituentCoverage;
import cn.sichu.market.mapper.IndexConstituentCoverageMapper;
import cn.sichu.market.mapper.IndexConstituentMapper;
import cn.sichu.market.service.IIndexConstituentService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import utils.DateTimeUtils;

import java.time.LocalDate;
import java.util.List;

/**
 * 指数成分时点查询: 有效 ⇔ in_date &lt;= D 且 (out_date 为空或 &gt; D)
 *
 * @author sichu huang
 * @since 2026/10/16
 **/
@Service
@RequiredArgsConstructor
public class IndexConstituentServiceImpl implements IIndexConstituentService {

    private final IndexConstituentMapper indexConstituentMapper;
    private final IndexConstituentCoverageMapper indexConstituentCoverageMapper;

    @Override
    public ConstituentSnapshot listConstituents(String indexSymbol, LocalDate date) {
        IndexConstituentCoverage coverage = indexConstituentCoverageMapper.selectOne(
            new LambdaQueryWrapper<IndexConstituentCoverage>().eq(IndexConstituentCoverage::getIndexSymbol, indexSymbol),
            false);
        if (coverage == null) {
            throw new BusinessException("指数成分时点表没有 " + indexSymbol);
        }
        if (coverage.getPartialFrom() == null || date.isBefore(coverage.getPartialFrom())) {
            throw new BusinessException(
                indexSymbol + " 成分记录从 " + coverage.getPartialFrom() + " 起, 查不了 " + date.format(DateTimeUtils.YYYY_MM_DD));
        }
        List<IndexConstituent> members = indexConstituentMapper.selectList(
            new LambdaQueryWrapper<IndexConstituent>().eq(IndexConstituent::getIndexSymbol, indexSymbol)
                .le(IndexConstituent::getInDate, date)
                .and(w -> w.isNull(IndexConstituent::getOutDate).or().gt(IndexConstituent::getOutDate, date))
                .orderByAsc(IndexConstituent::getConCode));
        boolean complete = coverage.getPitFrom() != null && !date.isBefore(coverage.getPitFrom());
        String note = complete ? null
            : coverage.getIndexName() + " 在 " + coverage.getPitFrom() + " 之前只有当前存活者子集(" + members.size() + "/"
                + coverage.getNominalCount() + "), 缺之后被剔除的样本";
        return new ConstituentSnapshot(indexSymbol, date, complete, note, members);
    }

    @Override
    public List<IndexConstituent> listIndexesOf(String conSymbol, LocalDate date) {
        return indexConstituentMapper.selectList(
            new LambdaQueryWrapper<IndexConstituent>().eq(IndexConstituent::getConSymbol, conSymbol)
                .le(IndexConstituent::getInDate, date)
                .and(w -> w.isNull(IndexConstituent::getOutDate).or().gt(IndexConstituent::getOutDate, date))
                .orderByAsc(IndexConstituent::getIndexSymbol));
    }
}
