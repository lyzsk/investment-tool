package cn.sichu.market.service.impl;

import cn.sichu.market.entity.*;
import cn.sichu.market.mapper.*;
import cn.sichu.market.service.IMarketImportService;
import cn.sichu.system.config.ProjectConfig;
import com.fasterxml.jackson.databind.JsonNode;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import utils.CollectionUtils;
import utils.DateTimeUtils;
import utils.JsonUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Function;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
@Slf4j
@Service
@RequiredArgsConstructor
public class MarketImportServiceImpl implements IMarketImportService {
    /* 批量插入每批行数(MySQL 单条 SQL 不宜过大) */
    private static final int BATCH_SIZE = 1000;
    /* 系统写入人(同 MyMetaObjectHandler.getUserId) */
    private static final Long SYSTEM_USER = 1L;

    private final ProjectConfig projectConfig;
    private final SecurityMasterMapper securityMasterMapper;
    private final KlineDayMapper klineDayMapper;
    private final AdjustmentFactorMapper adjustmentFactorMapper;
    private final KlineMinuteMapper klineMinuteMapper;
    private final WatchlistInfoMapper watchlistInfoMapper;
    private final CallAuctionMapper callAuctionMapper;
    /* 历史回补每只票一个事务(整批一个事务会撑爆 undo, 且一只坏文件不该回滚全部) */
    private final TransactionTemplate transactionTemplate;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String importDaily(LocalDate tradeDate) throws Exception {
        Path dir = Paths.get(projectConfig.getMarket().getOutputDir(),
            tradeDate.format(DateTimeUtils.YYYY_MM_DD));
        for (String stage : List.of("security", "kline_day")) {
            if (!Files.exists(dir.resolve("DONE_" + stage))) {
                throw new BusinessException("采集未完成, 缺 " + dir.resolve("DONE_" + stage));
            }
        }
        String securitySummary = upsertSecurity(
            JsonUtils.readJsonl(dir.resolve("security_master.jsonl"), SecurityMaster.class));
        int klineCount = replaceKlineDay(tradeDate,
            JsonUtils.readJsonl(dir.resolve("kline_day.jsonl"), KlineDay.class));
        /* 第 2b 段: refresh_factors.py 校验通过的除权标的, 按标的整体替换因子 */
        int factorSymbols = 0;
        if (Files.exists(dir.resolve("DONE_factor")) && Files.exists(
            dir.resolve("adjustment_factor.jsonl"))) {
            Map<String, List<AdjustmentFactor>> bySymbol =
                JsonUtils.readJsonl(dir.resolve("adjustment_factor.jsonl"), AdjustmentFactor.class)
                    .stream().collect(Collectors.groupingBy(AdjustmentFactor::getSymbol));
            bySymbol.forEach(this::replaceFactors);
            factorSymbols = bySymbol.size();
        }
        String summary =
            "market 入库 " + tradeDate.format(DateTimeUtils.YYYY_MM_DD) + ": " + securitySummary
                + ", kline_day " + klineCount + " 行, 除权刷新因子 " + factorSymbols + " 只";
        log.info(summary);
        return summary;
    }

    /**
     * 有则更新(只在名称/ST/板块变化时 updateById)/无则批量插入; 不删除(退市股保留, 防幸存者偏差)
     *
     * @param incoming incoming
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/10/11
     **/
    private String upsertSecurity(List<SecurityMaster> incoming) {
        if (CollectionUtils.isEmpty(incoming)) {
            throw new BusinessException("security_master.jsonl 为空");
        }
        Map<String, SecurityMaster> existing = securityMasterMapper.selectList(null).stream()
            .collect(Collectors.toMap(SecurityMaster::getSymbol, Function.identity(), (a, b) -> a));
        LocalDateTime now = LocalDateTime.now();
        List<SecurityMaster> toInsert = new ArrayList<>();
        int updated = 0;
        for (SecurityMaster in : incoming) {
            SecurityMaster old = existing.get(in.getSymbol());
            if (old == null) {
                in.setCreateBy(SYSTEM_USER);
                in.setCreateTime(now);
                toInsert.add(in);
                continue;
            }
            if (!Objects.equals(old.getName(), in.getName()) || !Objects.equals(old.getIsSt(),
                in.getIsSt()) || !Objects.equals(old.getBoardType(), in.getBoardType())) {
                old.setName(in.getName());
                old.setIsSt(in.getIsSt());
                old.setBoardType(in.getBoardType());
                old.setSource(in.getSource());
                /* MyBatis-Plus 自带, 自动填 update_by/update_time */
                securityMasterMapper.updateById(old);
                updated++;
            }
        }
        CollectionUtils.partition(toInsert, BATCH_SIZE).forEach(securityMasterMapper::insertBatch);
        return "security_master 新增 " + toInsert.size() + " / 更新 " + updated;
    }

    /**
     * 该交易日先物理删除再批量插入
     *
     * @param tradeDate tradeDate
     * @param rows      rows
     * @return int
     * @author sichu huang
     * @since 2026/10/11
     **/
    private int replaceKlineDay(LocalDate tradeDate, List<KlineDay> rows) {
        if (CollectionUtils.isEmpty(rows)) {
            throw new BusinessException("kline_day.jsonl 为空");
        }
        for (KlineDay k : rows) {
            if (!tradeDate.equals(k.getTradeDate())) {
                throw new BusinessException(
                    "kline_day.jsonl 混入非 " + tradeDate + " 的行: " + k.getSymbol() + " "
                        + k.getTradeDate());
            }
        }
        int deleted = klineDayMapper.physicalDeleteByTradeDate(tradeDate);
        LocalDateTime now = LocalDateTime.now();
        rows.forEach(k -> {
            k.setCreateBy(SYSTEM_USER);
            k.setCreateTime(now);
        });
        CollectionUtils.partition(rows, BATCH_SIZE).forEach(klineDayMapper::insertBatch);
        log.info("kline_day {} 删旧 {} 行, 插新 {} 行", tradeDate, deleted, rows.size());
        return rows.size();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String importMinute(LocalDate tradeDate) throws Exception {
        Path dir = Paths.get(projectConfig.getMarket().getOutputDir(),
            tradeDate.format(DateTimeUtils.YYYY_MM_DD));
        for (String stage : List.of("watchlist", "kline_minute")) {
            if (!Files.exists(dir.resolve("DONE_" + stage))) {
                throw new BusinessException("采集未完成, 缺 " + dir.resolve("DONE_" + stage));
            }
        }
        /* 健壮性 H1 纵深: manifest 里分时缺失超阈值(与 collect_minute.py 同口径 max(20 只, 5%))=残缺, 不入库 */
        Path mf = dir.resolve("manifest.json");
        if (Files.exists(mf)) {
            JsonNode km =
                JsonUtils.objectMapper.readTree(mf.toFile()).path("stages").path("kline_minute");
            long symbols = km.path("symbols").asLong(0);
            long missing = km.path("missingCount").asLong(0);
            if (symbols > 0 && missing > Math.max(20, symbols * 0.05)) {
                throw new BusinessException(
                    "分时缺失超阈值: 缺 " + missing + "/" + symbols + " 只(manifest), 不入库");
            }
        }
        LocalDateTime now = LocalDateTime.now();
        List<WatchlistInfo> watchlist =
            JsonUtils.readJsonl(dir.resolve("watchlist_info.jsonl"), WatchlistInfo.class);
        List<KlineMinute> bars =
            JsonUtils.readJsonl(dir.resolve("kline_minute.jsonl"), KlineMinute.class);
        if (CollectionUtils.isEmpty(watchlist) || CollectionUtils.isEmpty(bars)) {
            throw new BusinessException(
                "关注集或分时为空: watchlist " + watchlist.size() + " / kline_minute "
                    + bars.size());
        }
        watchlist.forEach(w -> {
            w.setCreateBy(SYSTEM_USER);
            w.setCreateTime(now);
        });
        bars.forEach(b -> {
            b.setCreateBy(SYSTEM_USER);
            b.setCreateTime(now);
        });
        watchlistInfoMapper.physicalDeleteByTradeDate(tradeDate);
        CollectionUtils.partition(watchlist, BATCH_SIZE).forEach(watchlistInfoMapper::insertBatch);
        klineMinuteMapper.physicalDeleteByTradeDate(tradeDate);
        CollectionUtils.partition(bars, BATCH_SIZE).forEach(klineMinuteMapper::insertBatch);
        String summary =
            "market 分时入库 " + tradeDate.format(DateTimeUtils.YYYY_MM_DD) + ": watchlist_info "
                + watchlist.size() + " 只, kline_minute " + bars.size() + " 根";
        log.info(summary);
        return summary;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String importGlobal(LocalDate day) throws Exception {
        Path dir = Paths.get(projectConfig.getMarket().getOutputDir(),
            day.format(DateTimeUtils.YYYY_MM_DD));
        if (!Files.exists(dir.resolve("DONE_global"))) {
            throw new BusinessException("采集未完成, 缺 " + dir.resolve("DONE_global"));
        }
        String securitySummary = upsertSecurity(
            JsonUtils.readJsonl(dir.resolve("global_security.jsonl"), SecurityMaster.class));
        List<KlineDay> bars =
            JsonUtils.readJsonl(dir.resolve("global_kline.jsonl"), KlineDay.class);
        LocalDateTime now = LocalDateTime.now();
        for (KlineDay k : bars) {
            k.setCreateBy(SYSTEM_USER);
            k.setCreateTime(now);
            /* 外围各品种当地交易日不同, 逐个按 symbol+日删 */
            klineDayMapper.physicalDeleteBySymbolAndRange(k.getSymbol(), k.getTradeDate(),
                k.getTradeDate());
        }
        CollectionUtils.partition(bars, BATCH_SIZE).forEach(klineDayMapper::insertBatch);
        String summary =
            "market 外围入库 " + day.format(DateTimeUtils.YYYY_MM_DD) + ": " + securitySummary
                + ", kline_day " + bars.size() + " 行";
        log.info(summary);
        return summary;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String importAuction(LocalDate tradeDate, String phase) throws Exception {
        Path dir = Paths.get(projectConfig.getMarket().getOutputDir(),
            tradeDate.format(DateTimeUtils.YYYY_MM_DD));
        String p = phase.toLowerCase();
        if (!Files.exists(dir.resolve("DONE_auction_" + p))) {
            throw new BusinessException("采集未完成, 缺 " + dir.resolve("DONE_auction_" + p));
        }
        List<CallAuction> rows =
            JsonUtils.readJsonl(dir.resolve("call_auction_" + p + ".jsonl"), CallAuction.class);
        LocalDateTime now = LocalDateTime.now();
        rows.forEach(a -> {
            a.setCreateBy(SYSTEM_USER);
            a.setCreateTime(now);
        });
        int deleted = callAuctionMapper.physicalDeleteByTradeDateAndPhase(tradeDate, phase);
        CollectionUtils.partition(rows, BATCH_SIZE).forEach(callAuctionMapper::insertBatch);
        String summary =
            "market 竞价入库 " + tradeDate.format(DateTimeUtils.YYYY_MM_DD) + " " + phase + ": 删旧 "
                + deleted + " / 插新 " + rows.size() + " 行(" + rows.stream()
                .map(CallAuction::getSymbol).distinct().count() + " 只)";
        log.info(summary);
        return summary;
    }

    @Override
    public String importHistory() throws Exception {
        Path dir = Paths.get(projectConfig.getMarket().getOutputDir(), "history");
        if (!Files.exists(dir.resolve("DONE_basic"))) {
            throw new BusinessException("历史回补基本资料未完成, 缺 " + dir.resolve("DONE_basic"));
        }
        String basicSummary = upsertSecurityBasic(
            JsonUtils.readJsonl(dir.resolve("security_basic.jsonl"), SecurityMaster.class));
        List<Path> files;
        try (Stream<Path> s = Files.list(dir.resolve("kline_day"))) {
            /* 只认写完的 .jsonl, 跳过回补脚本正在写的 .tmp */
            files = s.filter(p -> p.getFileName().toString().endsWith(".jsonl")).sorted().toList();
        }
        LocalDate liveFrom = projectConfig.getMarket().getReconcileStartDate();
        int symbols = 0;
        long klineRows = 0;
        long factorRows = 0;
        List<String> failed = new ArrayList<>();
        for (Path kf : files) {
            String symbol = kf.getFileName().toString().replace(".jsonl", "");
            try {
                /* 行情库上线日起的日线归每日流水线(新浪快照, 带成交额/换手率), 历史回补只管之前的, 防腾讯行(无成交额)覆盖快照行 */
                List<KlineDay> bars = JsonUtils.readJsonl(kf, KlineDay.class).stream()
                    .filter(k -> k.getTradeDate().isBefore(liveFrom)).toList();
                Path ff = dir.resolve("adjustment_factor").resolve(symbol + ".jsonl");
                List<AdjustmentFactor> factors =
                    Files.exists(ff) ? JsonUtils.readJsonl(ff, AdjustmentFactor.class) : List.of();
                transactionTemplate.executeWithoutResult(status -> {
                    replaceKlineRange(symbol, bars);
                    replaceFactorsFromHistory(symbol, factors);
                });
                symbols++;
                klineRows += bars.size();
                factorRows += factors.size();
            } catch (Exception e) {
                /* 单票失败不阻断, 汇总进结果; 修好文件重跑即可(幂等) */
                failed.add(symbol);
                log.error("历史回补入库失败 {}", symbol, e);
            }
            if ((symbols + failed.size()) % 500 == 0) {
                log.info("历史回补入库进度 {}/{} kline_day {} 行", symbols, files.size(),
                    klineRows);
            }
        }
        String summary =
            "market 历史入库: " + basicSummary + ", 标的 " + symbols + "/" + files.size()
                + ", kline_day " + klineRows + " 行, adjustment_factor " + factorRows + " 行" + (
                failed.isEmpty() ? "" :
                    ", 失败 " + failed.size() + " 只: " + failed.stream().limit(20).toList());
        log.info(summary);
        return summary;
    }

    /**
     * 历史基本资料: 已有标的只补上市/退市日(名称/ST 以每日快照为准, 不用 baostock 覆盖); 缺失标的(退市股等)补行
     *
     * @param incoming incoming
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/10/11
     **/
    private String upsertSecurityBasic(List<SecurityMaster> incoming) {
        if (CollectionUtils.isEmpty(incoming)) {
            throw new BusinessException("security_basic.jsonl 为空");
        }
        Map<String, SecurityMaster> existing = securityMasterMapper.selectList(null).stream()
            .collect(Collectors.toMap(SecurityMaster::getSymbol, Function.identity(), (a, b) -> a));
        LocalDateTime now = LocalDateTime.now();
        List<SecurityMaster> toInsert = new ArrayList<>();
        int updated = 0;
        for (SecurityMaster in : incoming) {
            SecurityMaster old = existing.get(in.getSymbol());
            if (old == null) {
                in.setIsSt(in.getName() != null && in.getName().contains("ST") ? 1 : 0);
                in.setCreateBy(SYSTEM_USER);
                in.setCreateTime(now);
                toInsert.add(in);
                continue;
            }
            if (!Objects.equals(old.getListDate(), in.getListDate()) || !Objects.equals(
                old.getDelistDate(), in.getDelistDate())) {
                old.setListDate(in.getListDate());
                old.setDelistDate(in.getDelistDate());
                securityMasterMapper.updateById(old);
                updated++;
            }
        }
        CollectionUtils.partition(toInsert, BATCH_SIZE).forEach(securityMasterMapper::insertBatch);
        return "security_master 补行 " + toInsert.size() + " / 补上市退市日 " + updated;
    }

    /**
     * 某标的按回补文件首尾日期区间先物理删除再批量插入(与当日快照重叠的日子一并覆盖)
     *
     * @param symbol symbol
     * @param bars   bars
     * @author sichu huang
     * @since 2026/10/11
     **/
    private void replaceKlineRange(String symbol, List<KlineDay> bars) {
        if (CollectionUtils.isEmpty(bars)) {
            return;
        }
        LocalDate from = bars.stream().map(KlineDay::getTradeDate).min(LocalDate::compareTo).get();
        LocalDate to = bars.stream().map(KlineDay::getTradeDate).max(LocalDate::compareTo).get();
        LocalDateTime now = LocalDateTime.now();
        bars.forEach(k -> {
            k.setCreateBy(SYSTEM_USER);
            k.setCreateTime(now);
        });
        klineDayMapper.physicalDeleteBySymbolAndRange(symbol, from, to);
        CollectionUtils.partition(bars, BATCH_SIZE).forEach(klineDayMapper::insertBatch);
    }

    /**
     * 某标的复权因子先物理删除再批量插入
     *
     * @param symbol  symbol
     * @param factors factors
     * @author sichu huang
     * @since 2026/10/11
     **/
    private void replaceFactors(String symbol, List<AdjustmentFactor> factors) {
        /* 10/17 健壮性 M8: 空列表原先先删光再 return(新浪 hfq 404/格式变化 → 该票因子被清空, 前复权全错); 改为空列表不动库 */
        if (CollectionUtils.isEmpty(factors)) {
            return;
        }
        adjustmentFactorMapper.physicalDeleteBySymbol(symbol);
        LocalDateTime now = LocalDateTime.now();
        factors.forEach(f -> {
            f.setCreateBy(SYSTEM_USER);
            f.setCreateTime(now);
        });
        CollectionUtils.partition(factors, BATCH_SIZE).forEach(adjustmentFactorMapper::insertBatch);
    }

    /**
     * 历史回补路径专用: 文件里最后一个除权日早于库里的(库里已有 refresh_factors 刷进来的新除权)就不替换, 防止重跑 importHistory 把新因子回退
     *
     * @author sichu huang
     * @param symbol symbol
     * @param factors factors
     * @since 2026/10/17
     **/
    private void replaceFactorsFromHistory(String symbol, List<AdjustmentFactor> factors) {
        if (CollectionUtils.isEmpty(factors)) {
            return;
        }
        LocalDate fileLast = factors.stream().map(AdjustmentFactor::getExDate).filter(java.util.Objects::nonNull)
            .max(LocalDate::compareTo).orElse(null);
        AdjustmentFactor dbLast = adjustmentFactorMapper.selectOne(
            new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<AdjustmentFactor>()
                .eq(AdjustmentFactor::getSymbol, symbol).orderByDesc(AdjustmentFactor::getExDate).last("limit 1"));
        if (dbLast != null && dbLast.getExDate() != null && fileLast != null && fileLast.isBefore(dbLast.getExDate())) {
            log.warn("importHistory 跳过因子替换 {}: 文件末除权日 {} 早于库里 {}(保留库里较新的因子)", symbol, fileLast,
                dbLast.getExDate());
            return;
        }
        replaceFactors(symbol, factors);
    }
}
