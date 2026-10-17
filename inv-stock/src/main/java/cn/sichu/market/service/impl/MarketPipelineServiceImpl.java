package cn.sichu.market.service.impl;

import cn.sichu.market.entity.CallAuction;
import cn.sichu.market.entity.KlineDay;
import cn.sichu.market.entity.KlineMinute;
import cn.sichu.market.entity.WatchlistInfo;
import cn.sichu.market.mapper.CallAuctionMapper;
import cn.sichu.market.mapper.KlineDayMapper;
import cn.sichu.market.mapper.KlineMinuteMapper;
import cn.sichu.market.mapper.WatchlistInfoMapper;
import cn.sichu.market.service.IMarketImportService;
import cn.sichu.market.service.IMarketPipelineService;
import cn.sichu.reconcile.entity.ReconcileResult;
import cn.sichu.reconcile.service.IReconcileResultService;
import cn.sichu.system.config.ProjectConfig;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import utils.DateTimeUtils;
import utils.JsonUtils;
import utils.ProcessUtils;
import utils.TradingDayUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.locks.ReentrantLock;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Slf4j
@Service
@RequiredArgsConstructor
public class MarketPipelineServiceImpl implements IMarketPipelineService {
    /* 分时覆盖率下限: 分时 distinct symbol ≥ 关注集 × 95%(H1; 与 collect_minute.py 完成阈值 max(20只,5%) 同量级) */
    private static final double MIN_MINUTE_COVERAGE = 0.95;
    private static final String BIZ = "MARKET";
    /* 收盘快照可取的时间: 交易日 15:30 后到下一交易日 09:15 前 */
    private static final LocalTime CLOSE_READY = LocalTime.of(15, 30);
    private static final LocalTime NEXT_OPEN = LocalTime.of(9, 15);
    /* 全市场日线低于此行数视为不完整(10/09 实测 8123 行, 停牌多的日子也远高于此) */
    private static final long MIN_DAY_ROWS = 5000;
    private final WatchlistInfoMapper watchlistInfoMapper;
    private final ProjectConfig projectConfig;
    private final IMarketImportService marketImportService;
    private final IReconcileResultService reconcileResultService;
    private final KlineDayMapper klineDayMapper;
    private final KlineMinuteMapper klineMinuteMapper;
    private final CallAuctionMapper callAuctionMapper;
    private final ReentrantLock lock = new ReentrantLock();

    @Override
    public String runDay(LocalDate day) throws Exception {
        if (!lock.tryLock()) {
            throw new BusinessException(
                "另一条行情流水线正在跑(收盘任务/对账补采), 本次 " + day + " 放弃, 稍后对账会补");
        }
        try {
            return doRunDay(day);
        } finally {
            lock.unlock();
        }
    }

    /**
     * 见 runDay; 调用方须已持锁
     *
     * @param day day
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/10/12
     **/
    private String doRunDay(LocalDate day) throws Exception {
        String d = day.format(DateTimeUtils.YYYY_MM_DD);
        Path dir = Paths.get(projectConfig.getMarket().getOutputDir(), d);
        String rootDir = projectConfig.getRootDir();
        long timeoutMin = projectConfig.getMarket().getCollectTimeoutMin();
        List<String> steps = new ArrayList<>();
        if (!Files.exists(dir.resolve("DONE_kline_day"))) {
            if (snapshotAvailable(day)) {
                /* 脚本识别出的交易日≠day(源未更新)时报错退出, 防把昨日数据当今日入库 */
                ProcessUtils.runChecked(command(rootDir, "node",
                    Paths.get(rootDir, "scripts", "market", "collect_daily.mjs").toString(),
                    "--expect", d), timeoutMin, "collect_daily.mjs");
                steps.add("新浪快照采集");
            } else {
                ProcessUtils.runChecked(
                    command(rootDir, ProcessUtils.venvPython(rootDir), "-X", "utf8",
                        Paths.get(rootDir, "scripts", "market", "backfill_history.py").toString(),
                        "--day", d), projectConfig.getMarket().getCatchUpTimeoutMin(),
                    "backfill_history.py --day");
                steps.add("腾讯补采");
            }
        }
        /* 除权检测失败不挡日线入库(因子缺一天, 次日 factor_pending 机制会重试) */
        try {
            ProcessUtils.runChecked(command(rootDir, ProcessUtils.venvPython(rootDir), "-X", "utf8",
                Paths.get(rootDir, "scripts", "market", "refresh_factors.py").toString(), "--date",
                d), timeoutMin, "refresh_factors.py");
        } catch (Exception e) {
            log.warn("除权检测失败(日线照常入库) {}: {}", d, e.getMessage());
            steps.add("除权检测失败");
        }
        String result = marketImportService.importDaily(day);
        /* 分时依赖当日日线判涨跌停, 必须在日线之后; 分时失败不回滚已入库的日线, 但整体记为失败便于发现 */
        try {
            if (!Files.exists(dir.resolve("DONE_kline_minute"))) {
                ProcessUtils.runChecked(
                    command(rootDir, ProcessUtils.venvPython(rootDir), "-X", "utf8",
                        Paths.get(rootDir, "scripts", "market", "collect_minute.py").toString(),
                        "--date", d), timeoutMin, "collect_minute.py");
            }
            result += "; " + marketImportService.importMinute(day);
        } catch (Exception e) {
            log.error("分时段失败(日线已入库) {}", d, e);
            throw new BusinessException(result + "; 分时段失败: " + e.getMessage());
        }
        return (steps.isEmpty() ? "" : steps + " ") + result;
    }

    /**
     * 新浪快照此刻是否还是 day 的收盘数据
     *
     * @param day day
     * @return boolean
     * @author sichu huang
     * @since 2026/10/12
     **/
    private boolean snapshotAvailable(LocalDate day) {
        LocalDateTime now = LocalDateTime.now();
        LocalDate next = TradingDayUtils.getNextTradingDay(day);
        return !now.isBefore(day.atTime(CLOSE_READY)) && now.isBefore(next.atTime(NEXT_OPEN));
    }

    private ProcessBuilder command(String rootDir, String... args) {
        ProcessBuilder pb = new ProcessBuilder(args);
        pb.directory(Paths.get(rootDir).toFile());
        return pb;
    }

    @Override
    public LocalDate latestClosedTradingDay() {
        LocalDateTime now = LocalDateTime.now();
        LocalDate today = now.toLocalDate();
        if (TradingDayUtils.isTradingDay(today) && !now.toLocalTime().isBefore(CLOSE_READY)) {
            return today;
        }
        return TradingDayUtils.getPreviousTradingDay(today);
    }

    @Override
    public String reconcile() throws Exception {
        if (!lock.tryLock()) {
            return "行情流水线正在跑, 本次对账跳过";
        }
        try {
            ProjectConfig.Market cfg = projectConfig.getMarket();
            String batchNo = reconcileResultService.newBatchNo(BIZ);
            List<LocalDate> days = new ArrayList<>();
            LocalDate d = latestClosedTradingDay();
            while (days.size() < cfg.getReconcileLookbackDays() && !d.isBefore(
                cfg.getReconcileStartDate())) {
                days.add(0, d);
                d = TradingDayUtils.getPreviousTradingDay(d);
            }
            List<ReconcileResult> rows = new ArrayList<>();
            for (LocalDate day : days) {
                rows.addAll(reconcileDay(batchNo, day));
            }
            return reconcileResultService.saveAndNotify("行情库对账", rows);
        } finally {
            lock.unlock();
        }
    }

    /**
     * 单日对账: 缺日线/分时就补(持锁调用 doRunDay), 补完复核行数
     *
     * @param batchNo batchNo
     * @param day     day
     * @return java.util.List<cn.sichu.reconcile.entity.ReconcileResult>
     * @author sichu huang
     * @since 2026/10/12
     **/
    private List<ReconcileResult> reconcileDay(String batchNo, LocalDate day) {
        String key = day.format(DateTimeUtils.YYYY_MM_DD);
        List<ReconcileResult> rows = new ArrayList<>();
        long dayRows = countDay(day);
        long minuteRows = countMinute(day);
        long watch = countWatch(day);
        long minuteSyms = klineMinuteMapper.countDistinctSymbol(day);
        boolean dayOk = dayRows >= MIN_DAY_ROWS;
        /* 10/17 健壮性 H1: 分时按覆盖率判(distinct symbol ≥ 关注集 × 95%); 原 minuteRows > 0 时缺 40% 也判 OK、不补采 */
        boolean minuteOk = minuteRows > 0 && watch > 0 && minuteSyms >= Math.ceil(watch * MIN_MINUTE_COVERAGE);
        String minuteExpect = "symbol≥" + (long) Math.ceil(watch * MIN_MINUTE_COVERAGE) + "/" + watch;
        if (dayOk && minuteOk) {
            rows.add(reconcileResultService.of(batchNo, BIZ, key, "kline_day", "≥" + MIN_DAY_ROWS,
                dayRows, "OK", null));
            rows.add(
                reconcileResultService.of(batchNo, BIZ, key, "kline_minute", minuteExpect,
                    minuteSyms + "只/" + minuteRows + "根", "OK", null));
        } else {
            String detail;
            String result;
            try {
                detail = doRunDay(day);
                result = "FIXED";
            } catch (Exception e) {
                log.error("对账补采失败 {}", key, e);
                detail = e.getMessage();
                result = "FAILED";
            }
            long dayAfter = countDay(day);
            long minuteAfter = countMinute(day);
            long symsAfter = klineMinuteMapper.countDistinctSymbol(day);
            long watchAfter = countWatch(day);
            boolean minuteOkAfter = minuteAfter > 0 && watchAfter > 0 && symsAfter >= Math.ceil(watchAfter * MIN_MINUTE_COVERAGE);
            rows.add(reconcileResultService.of(batchNo, BIZ, key, "kline_day", "≥" + MIN_DAY_ROWS,
                dayRows + "→" + dayAfter,
                dayOk ? "OK" : dayAfter >= MIN_DAY_ROWS ? result : "FAILED", detail));
            rows.add(reconcileResultService.of(batchNo, BIZ, key, "kline_minute", minuteExpect,
                minuteSyms + "→" + symsAfter + "只",
                minuteOk ? "OK" : minuteOkAfter ? result : "FAILED", detail));
        }
        if (!day.isBefore(projectConfig.getMarket().getAuctionStartDate())) {
            long auctionRows = callAuctionMapper.selectCount(
                new LambdaQueryWrapper<CallAuction>().eq(CallAuction::getTradeDate, day)
                    .eq(CallAuction::getPhase, "OPEN"));
            rows.add(reconcileResultService.of(batchNo, BIZ, key, "call_auction", ">0", auctionRows,
                auctionRows > 0 ? "OK" : "UNRECOVERABLE", auctionRows > 0 ? null :
                    "开盘竞价过程错过不可补(09:25 撮合价可看 kline_minute 首根)"));
        }
        rows.add(factorCheck(batchNo, day, key));
        return rows;
    }

    /**
     * 除权因子: 读当日 manifest.factor, 有超期未校验通过的记 WARN
     *
     * @param batchNo batchNo
     * @param day     day
     * @param key     key
     * @return cn.sichu.reconcile.entity.ReconcileResult
     * @author sichu huang
     * @since 2026/10/12
     **/
    private ReconcileResult factorCheck(String batchNo, LocalDate day, String key) {
        Path mf = Paths.get(projectConfig.getMarket().getOutputDir(), key, "manifest.json");
        try {
            JsonNode factor =
                Files.exists(mf) ? JsonUtils.objectMapper.readTree(mf.toFile()).path("factor") :
                    null;
            if (factor == null || factor.isMissingNode()) {
                return reconcileResultService.of(batchNo, BIZ, key, "adjustment_factor", "已检测",
                    "未检测", "WARN", "当日无除权检测记录(refresh_factors.py 未跑或失败)");
            }
            int refreshed = factor.path("refreshed").size();
            int expired = factor.path("expired").size();
            int pending = factor.path("pending").size();
            return reconcileResultService.of(batchNo, BIZ, key, "adjustment_factor", "候选全刷新",
                "刷新" + refreshed + "/待重试" + pending + "/超期" + expired,
                expired > 0 ? "WARN" : "OK",
                expired > 0 ? "因子校验超期: " + factor.path("expired") : null);
        } catch (Exception e) {
            return reconcileResultService.of(batchNo, BIZ, key, "adjustment_factor", "已检测",
                "读取失败", "WARN", e.getMessage());
        }
    }

    private long countDay(LocalDate day) {
        return klineDayMapper.selectCount(
            new LambdaQueryWrapper<KlineDay>().eq(KlineDay::getTradeDate, day));
    }

    private long countMinute(LocalDate day) {
        return klineMinuteMapper.selectCount(
            new LambdaQueryWrapper<KlineMinute>().eq(KlineMinute::getTradeDate, day));
    }

    private long countWatch(LocalDate day) {
        return watchlistInfoMapper.selectCount(
            new LambdaQueryWrapper<WatchlistInfo>().eq(WatchlistInfo::getTradeDate, day));
    }
}
