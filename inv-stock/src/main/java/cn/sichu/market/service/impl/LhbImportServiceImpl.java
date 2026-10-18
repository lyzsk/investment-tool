package cn.sichu.market.service.impl;

import cn.sichu.market.entity.LhbSeat;
import cn.sichu.market.entity.LhbStock;
import cn.sichu.market.mapper.LhbSeatMapper;
import cn.sichu.market.mapper.LhbStockMapper;
import cn.sichu.market.service.ILhbImportService;
import cn.sichu.system.config.ProjectConfig;
import com.fasterxml.jackson.databind.JsonNode;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import utils.CollectionUtils;
import utils.DateTimeUtils;
import utils.JsonUtils;
import utils.StringUtils;
import utils.TradingDayUtils;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * 龙虎榜入库: 口径与 scripts/lhb/import_lhb_db.py(10/15 一次性导入历史用)逐字段一致
 *
 * @author sichu huang
 * @since 2026/10/15
 **/
@Slf4j
@Service
@RequiredArgsConstructor
public class LhbImportServiceImpl implements ILhbImportService {
    /* 批量插入每批行数 */
    private static final int BATCH_SIZE = 1000;
    /* 系统写入人(同 MyMetaObjectHandler.getUserId) */
    private static final Long SYSTEM_USER = 1L;
    /* 交易所 16:30~17:30 出齐, 东财晚几分钟; 18:00 前抓的 list.json 是临时版(同 fetch_lhb.mjs READY_HHMM) */
    private static final String READY_HHMM = "18:00";
    /* 机构席位: 主板=机构专用; 北交所/可转债榜=机构投资者/机构 */
    private static final Pattern INSTITUTION = Pattern.compile("^机构(专用|投资者)?$");
    /* 席位简称(同 fetch_lhb.mjs seatShort): 去公司后缀与"证券"/"营业部", 形如 "华鑫 上海宛平南路" */
    private static final Pattern SEAT_NAME = Pattern.compile("^(.*?)(股份有限公司|有限责任公司|有限公司)(.*)$");

    private final ProjectConfig projectConfig;
    private final LhbStockMapper lhbStockMapper;
    private final LhbSeatMapper lhbSeatMapper;
    /* 每个交易日一个事务(importRecent/importAll 逐日调, 单日失败不回滚其他日) */
    private final TransactionTemplate transactionTemplate;

    /**
     * 一个交易日解析结果
     *
     * @author sichu huang
     * @since 2026/10/15
     **/
    public record LhbDay(List<LhbStock> stocks, List<LhbSeat> seats) {
    }

    @Override
    public String importDay(LocalDate tradeDate) throws Exception {
        LhbDay day = parseDay(lhbDir(tradeDate), tradeDate, loadYouzi());
        LocalDateTime now = LocalDateTime.now();
        day.stocks().forEach(s -> {
            s.setCreateBy(SYSTEM_USER);
            s.setCreateTime(now);
        });
        day.seats().forEach(s -> {
            s.setCreateBy(SYSTEM_USER);
            s.setCreateTime(now);
        });
        transactionTemplate.executeWithoutResult(status -> {
            lhbStockMapper.physicalDeleteByTradeDate(tradeDate);
            lhbSeatMapper.physicalDeleteByTradeDate(tradeDate);
            CollectionUtils.partition(day.stocks(), BATCH_SIZE).forEach(lhbStockMapper::insertBatch);
            CollectionUtils.partition(day.seats(), BATCH_SIZE).forEach(lhbSeatMapper::insertBatch);
        });
        String summary = "龙虎榜入库 " + tradeDate.format(DateTimeUtils.YYYY_MM_DD) + ": lhb_stock " + day.stocks().size()
            + " 行(" + day.stocks().stream().filter(s -> s.getIsPrimary() == 1).count() + " 只), lhb_seat " + day.seats().size()
            + " 行";
        log.info(summary);
        return summary;
    }

    @Override
    public String importRecent(int lookbackDays) throws Exception {
        LocalDate d = LocalDate.now();
        if (!TradingDayUtils.isTradingDay(d)) {
            d = TradingDayUtils.getPreviousTradingDay(d);
        }
        List<String> done = new ArrayList<>();
        List<String> skipped = new ArrayList<>();
        for (int i = 0; i < lookbackDays; i++, d = TradingDayUtils.getPreviousTradingDay(d)) {
            try {
                importDay(d);
                done.add(d.format(DateTimeUtils.YYYY_MM_DD));
            } catch (BusinessException e) {
                /* 未就绪(没抓/临时版/缺 detail)=正常情况, 下一轮再导 */
                skipped.add(d.format(DateTimeUtils.YYYY_MM_DD) + "(" + e.getMessage() + ")");
            }
        }
        String summary = "龙虎榜每日入库: 重导 " + done.size() + " 天 " + done + (skipped.isEmpty() ? "" : ", 未就绪跳过 " + skipped);
        log.info(summary);
        return summary;
    }

    @Override
    public String importAll() throws Exception {
        Path root = Paths.get(projectConfig.getFile().getDownload().getRootDir(), "lhb");
        List<LocalDate> days;
        try (Stream<Path> s = Files.list(root)) {
            days = s.map(p -> p.getFileName().toString()).filter(n -> n.matches("\\d{4}\\.\\d{2}\\.\\d{2}")).sorted()
                .map(n -> LocalDate.parse(n, DateTimeUtils.YYYYMMDD_DOT)).toList();
        }
        int ok = 0;
        List<String> failed = new ArrayList<>();
        for (LocalDate d : days) {
            try {
                importDay(d);
                ok++;
            } catch (Exception e) {
                failed.add(d.format(DateTimeUtils.YYYY_MM_DD) + "(" + e.getMessage() + ")");
                log.warn("龙虎榜历史入库跳过 {}: {}", d, e.getMessage());
            }
        }
        String summary = "龙虎榜历史入库: " + ok + "/" + days.size() + " 天" + (failed.isEmpty() ? "" :
            ", 跳过 " + failed.size() + " 天: " + failed.stream().limit(20).toList());
        log.info(summary);
        return summary;
    }

    /**
     * 解析一个交易日目录(纯函数, 不碰库): lhb_stock=list.json 每条上榜记录一行; lhb_seat=detail 买五/卖五每行一行
     *
     * @author sichu huang
     * @param dir downloads/lhb/yyyy.MM.dd
     * @param tradeDate tradeDate
     * @param youzi 席位简称 → 游资别名(youzi.json 的 map)
     * @since 2026/10/15
     * @return cn.sichu.market.service.impl.LhbImportServiceImpl.LhbDay
     **/
    public static LhbDay parseDay(Path dir, LocalDate tradeDate, Map<String, String> youzi) throws Exception {
        String date = tradeDate.format(DateTimeUtils.YYYY_MM_DD);
        Path listFile = dir.resolve("list.json");
        if (!Files.exists(listFile)) {
            throw new BusinessException("未采集, 缺 " + listFile);
        }
        JsonNode list = JsonUtils.objectMapper.readTree(listFile.toFile());
        String fetchedAt = list.path("fetched_at").asText("");
        JsonNode rows = list.path("rows");
        if (!rows.isArray() || rows.isEmpty()) {
            throw new BusinessException("空榜 " + listFile);
        }
        if (fetchedAt.compareTo(date + " " + READY_HHMM) < 0) {
            throw new BusinessException("临时版(抓取 " + fetchedAt + ")");
        }
        String source = list.path("source").asText("em");
        LocalDateTime fetched = LocalDateTime.parse(fetchedAt, DateTimeUtils.YYYY_MM_DD_HH_MM_SS);
        /* 一只票多条上榜记录(当日口径+多日累计), 保持原顺序分组 */
        Map<String, List<JsonNode>> byCode = new LinkedHashMap<>();
        rows.forEach(r -> byCode.computeIfAbsent(r.path("SECURITY_CODE").asText(), k -> new ArrayList<>()).add(r));
        List<LhbStock> stocks = new ArrayList<>();
        List<LhbSeat> seats = new ArrayList<>();
        for (Map.Entry<String, List<JsonNode>> e : byCode.entrySet()) {
            String code = e.getKey();
            JsonNode prim = e.getValue().stream().filter(r -> !isMultiDay(r)).findFirst().orElse(e.getValue().get(0));
            String primSymbol = symbolOf(prim.path("SECUCODE").asText(""), code);
            for (JsonNode r : e.getValue()) {
                LhbStock s = new LhbStock();
                s.setTradeDate(tradeDate);
                s.setSymbol(symbolOf(r.path("SECUCODE").asText(""), code));
                s.setCode(code);
                s.setName(text(r, "SECURITY_NAME_ABBR"));
                s.setTradeId(r.path("TRADE_ID").asLong());
                s.setIsPrimary(r == prim ? 1 : 0);
                s.setReason(text(r, "EXPLANATION"));
                s.setClosePrice(dec(r, "CLOSE_PRICE"));
                s.setChangeRate(dec(r, "CHANGE_RATE"));
                s.setBuyAmt(dec(r, "BILLBOARD_BUY_AMT"));
                s.setSellAmt(dec(r, "BILLBOARD_SELL_AMT"));
                s.setNetAmt(dec(r, "BILLBOARD_NET_AMT"));
                s.setDealNetRatio(dec(r, "DEAL_NET_RATIO"));
                s.setDealAmount(dec(r, "ACCUM_AMOUNT"));
                s.setTurnoverRate(dec(r, "TURNOVERRATE"));
                s.setTradeMarket(text(r, "TRADE_MARKET"));
                s.setFetchedAt(fetched);
                s.setSource(source);
                s.setStatus(0);
                stocks.add(s);
            }
            Path detailFile = dir.resolve("detail_" + code + ".json");
            if (!Files.exists(detailFile)) {
                throw new BusinessException("不完整, 缺 " + detailFile.getFileName());
            }
            JsonNode detail = JsonUtils.objectMapper.readTree(detailFile.toFile());
            for (String side : List.of("BUY", "SELL")) {
                /* 按 trade_id 分组后组内按该方向金额降序排名次, 同额按营业部编码 */
                Map<String, List<JsonNode>> byTrade = new LinkedHashMap<>();
                detail.path(side.toLowerCase()).forEach(
                    x -> byTrade.computeIfAbsent(x.path("TRADE_ID").asText(), k -> new ArrayList<>()).add(x));
                for (Map.Entry<String, List<JsonNode>> t : byTrade.entrySet()) {
                    List<JsonNode> xs = new ArrayList<>(t.getValue());
                    xs.sort(Comparator.comparing((JsonNode x) -> amountOf(x, side)).reversed()
                        .thenComparing(x -> x.path("OPERATEDEPT_CODE").asText("")));
                    int rank = 0;
                    for (JsonNode x : xs) {
                        String name = StringUtils.isEmpty(text(x, "OPERATEDEPT_NAME")) ? "" : text(x, "OPERATEDEPT_NAME").trim();
                        LhbSeat s = new LhbSeat();
                        s.setTradeDate(tradeDate);
                        s.setSymbol(primSymbol);
                        s.setCode(code);
                        s.setTradeId(Long.parseLong(t.getKey()));
                        s.setDirection(side);
                        s.setSeatRank(++rank);
                        s.setDeptCode(text(x, "OPERATEDEPT_CODE"));
                        s.setDeptName(name);
                        s.setAmount(dec(x, side));
                        s.setBuyAmt(dec(x, "BUY"));
                        s.setSellAmt(dec(x, "SELL"));
                        s.setNetAmt(dec(x, "NET"));
                        s.setBuyRatio(dec(x, "TOTAL_BUYRIO"));
                        s.setSellRatio(dec(x, "TOTAL_SELLRIO"));
                        s.setIsInstitution(INSTITUTION.matcher(name).matches() ? 1 : 0);
                        s.setYouziAlias(youzi.get(seatShort(name)));
                        s.setSource(source);
                        s.setStatus(0);
                        seats.add(s);
                    }
                }
            }
        }
        return new LhbDay(stocks, seats);
    }

    /**
     * 席位简称(同 fetch_lhb.mjs seatShort): "华鑫证券有限责任公司上海宛平南路证券营业部" → "华鑫 上海宛平南路"; 机构专用/深股通专用等原样
     *
     * @author sichu huang
     * @param fullName fullName
     * @since 2026/10/15
     * @return java.lang.String
     **/
    public static String seatShort(String fullName) {
        String n = fullName == null ? "" : fullName.trim();
        Matcher m = SEAT_NAME.matcher(n);
        if (!m.matches()) {
            return n;
        }
        String broker = m.group(1).replaceFirst("证券", "");
        String branch = m.group(3).replaceFirst("(证券)?营业部$", "").trim();
        return branch.isEmpty() ? broker : broker + " " + branch;
    }

    /**
     * 读 scripts/lhb/youzi.json 的 map(席位简称 → 游资别名; 用户可直接增删, 每次导入现读)
     *
     * @author sichu huang
     * @since 2026/10/15
     * @return java.util.Map<java.lang.String,java.lang.String>
     **/
    private Map<String, String> loadYouzi() throws Exception {
        Path f = Paths.get(projectConfig.getRootDir(), "scripts", "lhb", "youzi.json");
        Map<String, String> map = new HashMap<>();
        if (Files.exists(f)) {
            JsonNode m = JsonUtils.objectMapper.readTree(f.toFile()).path("map");
            m.fields().forEachRemaining(e -> map.put(e.getKey(), e.getValue().asText()));
        } else {
            log.warn("缺 {}, 游资别名全部留空", f);
        }
        return map;
    }

    private Path lhbDir(LocalDate tradeDate) {
        return Paths.get(projectConfig.getFile().getDownload().getRootDir(), "lhb",
            tradeDate.format(DateTimeUtils.YYYYMMDD_DOT));
    }

    /* 多日累计口径(连续 3 日/北交所连续 3 日/连续 10 日内多次异常), 同 fetch_lhb isThreeDay */
    private static boolean isMultiDay(JsonNode r) {
        return r.path("EXPLANATION").asText("").contains("连续");
    }

    /* SECUCODE 后缀 SH/SZ/BJ → security_master.symbol 前缀; 缺后缀按代码首位推断 */
    private static String symbolOf(String secuCode, String code) {
        int i = secuCode.lastIndexOf('.');
        String suffix = i >= 0 ? secuCode.substring(i + 1).toUpperCase() : "";
        String prefix = switch (suffix) {
            case "SH" -> "sh";
            case "SZ" -> "sz";
            case "BJ" -> "bj";
            default -> "0123".indexOf(code.charAt(0)) >= 0 ? "sz" : "sh";
        };
        return prefix + code;
    }

    private static String text(JsonNode n, String field) {
        JsonNode v = n.get(field);
        return v == null || v.isNull() ? null : v.asText();
    }

    /* 数值字段: 东财有时给字符串(明细 TRADE_ID), 文本按 BigDecimal 解析; 缺失/null → null */
    private static BigDecimal dec(JsonNode n, String field) {
        JsonNode v = n.get(field);
        if (v == null || v.isNull()) {
            return null;
        }
        if (v.isNumber()) {
            return v.isFloatingPointNumber() ? BigDecimal.valueOf(v.doubleValue()) : v.decimalValue();
        }
        String s = v.asText().trim();
        return s.isEmpty() ? null : new BigDecimal(s);
    }

    private static BigDecimal amountOf(JsonNode x, String side) {
        BigDecimal v = dec(x, side);
        return v == null ? BigDecimal.ZERO : v;
    }
}
