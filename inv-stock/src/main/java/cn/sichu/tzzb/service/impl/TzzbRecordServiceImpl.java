package cn.sichu.tzzb.service.impl;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.tzzb.entity.TzzbRecord;
import cn.sichu.tzzb.mapper.TzzbRecordMapper;
import cn.sichu.tzzb.service.ITzzbRecordService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import utils.DateTimeUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

/**
 *
 * @author sichu huang
 * @since 2026/10/01 23:47
 */
@Service
@RequiredArgsConstructor
public class TzzbRecordServiceImpl extends ServiceImpl<TzzbRecordMapper, TzzbRecord>
    implements ITzzbRecordService {

    private static final ObjectMapper OM = new ObjectMapper();
    private final ProjectConfig projectConfig;

    private static JsonNode pick(JsonNode n, String... names) {
        for (String name : names) {
            if (n.has(name) && !n.get(name).isNull()) {
                return n.get(name);
            }
        }
        return null;
    }

    private static String text(JsonNode n, String... names) {
        JsonNode v = pick(n, names);
        return v == null ? null : v.asText();
    }

    private static BigDecimal dec(JsonNode n, String... names) {
        String v = text(n, names);
        return v == null || v.isEmpty() ? null : new BigDecimal(v);
    }

    private boolean exists(String ledger, String type, LocalDateTime recordTime, String stockCode,
        String side) {
        return count(new LambdaQueryWrapper<TzzbRecord>().eq(TzzbRecord::getLedger, ledger)
            .eq(TzzbRecord::getRecordType, type).eq(TzzbRecord::getRecordTime, recordTime)
            .eq(stockCode != null, TzzbRecord::getStockCode, stockCode)
            .eq(side != null, TzzbRecord::getSide, side)) > 0;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String syncFromRawJson(String ledger) {
        Path dir = Paths.get(projectConfig.getFile().getDownload().getRootDir(), "tzzb", ledger);
        if (!Files.isDirectory(dir)) {
            throw new BusinessException(
                "downloads/tzzb/" + ledger + " 不存在, 先跑 node scripts/fetch_tzzb.mjs --ledger "
                    + ledger);
        }
        int[] ins = new int[4], skip =
            new int[4];   // 0=trade 1=nav_day 2=position_snap 3=bs_leg (nav_month 实测不可行已移除)
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(dir, "*.json")) {
            for (Path f : ds) {
                String name = f.getFileName().toString();
                JsonNode root = OM.readTree(Files.readString(f));
                JsonNode data = root.has("ex_data") ? root.get("ex_data") : root;   // 实测信封=ex_data
                if (name.startsWith("position_change_p")) {
                    JsonNode list = data.get("change_list");
                    if (list == null || !list.isArray()) {
                        continue;
                    }
                    for (JsonNode t : list) {
                        String time = text(t, "trans_date");   // "2026-09-30 09:30:03"
                        if (time == null) {
                            continue;
                        }
                        LocalDateTime recordTime = DateTimeUtils.parseLenient(time);
                        String code = text(t, "stock_code");
                        String side = text(t, "buy_sell");   // 全"9"未破译[?], 存原值
                        if (exists(ledger, "trade", recordTime, code, side)) {
                            skip[0]++;
                            continue;
                        }
                        TzzbRecord e = base(ledger, "trade", recordTime, t);
                        e.setStockCode(code);
                        e.setStockName(text(t, "stock_name"));
                        e.setSide(side);
                        e.setPrice(dec(t, "trans_price"));
                        e.setQty(dec(t, "trans_count"));     // 分享视图全空串→NULL
                        e.setAmount(dec(t, "trans_amount")); // 分享视图全空串→NULL
                        save(e);
                        ins[0]++;
                    }
                } else if (name.equals("nav_daily.json")) {
                    JsonNode list = data.get("index_list");
                    if (list == null || !list.isArray()) {
                        continue;
                    }
                    BigDecimal prevIndex = null;   // 逐日收益无现成字段, 由 index 链算
                    for (JsonNode t : list) {
                        String day = text(t, "date");   // "20260109"
                        if (day == null) {
                            continue;
                        }
                        LocalDateTime recordTime = DateTimeUtils.parseLenient(day).withHour(15);
                        BigDecimal index = dec(t, "index");
                        if (exists(ledger, "nav_day", recordTime, null, null)) {
                            skip[1]++;
                            prevIndex = index;   // 已入库的也要维护链算前值
                            continue;
                        }
                        TzzbRecord e = base(ledger, "nav_day", recordTime, t);
                        if (index != null && prevIndex != null && prevIndex.signum() != 0) {
                            e.setDailyReturnPct(index.divide(prevIndex, 8, RoundingMode.HALF_UP)
                                .subtract(BigDecimal.ONE).multiply(new BigDecimal("100")));
                        }
                        save(e);
                        ins[1]++;
                        prevIndex = index;
                    }
                } else if (name.startsWith("change_bs_")) {
                    // 逐笔买卖腿(change_bs_<code>_p<n>.json): op 实测 1=买入腿 2=卖出腿;
                    // qty/amount 此口径有真值(与 trade 日汇总全空不同); trans_date 秒级
                    JsonNode list = data.get("change_list");
                    if (list == null || !list.isArray()) {
                        continue;
                    }
                    for (JsonNode t : list) {
                        String time = text(t, "trans_date");   // "2026-09-30 09:30:03"
                        if (time == null) {
                            continue;
                        }
                        LocalDateTime recordTime = DateTimeUtils.parseLenient(time);
                        String code = text(t, "stock_code");
                        String op = text(t, "op");
                        String side = "1".equals(op) ? "买入" : "2".equals(op) ? "卖出" : op;
                        if (exists(ledger, "bs_leg", recordTime, code, side)) {
                            skip[3]++;
                            continue;
                        }
                        TzzbRecord e = base(ledger, "bs_leg", recordTime, t);
                        e.setStockCode(code);
                        e.setStockName(text(t, "stock_name"));
                        e.setSide(side);
                        e.setPrice(dec(t, "trans_price"));
                        e.setQty(dec(t, "trans_count"));
                        e.setAmount(dec(t, "trans_amount"));
                        save(e);
                        ins[3]++;
                    }
                } else if (name.equals("position.json")) {
                    // month.json 只有月份列表无收益数值, 不入库
                    JsonNode list = data.get("position_list");
                    LocalDateTime snapTime = LocalDateTime.now().withNano(0);
                    if (list != null && list.isArray()) {
                        for (JsonNode t : list) {
                            TzzbRecord e = base(ledger, "position_snap", snapTime, t);
                            e.setStockCode(text(t, "stock_code"));
                            e.setStockName(text(t, "stock_name"));
                            // position_percent 无专用列, 留 payload_json;
                            // 空仓快照照常入表(10/1 用户定: 日内选手每日归零是纪律信号)
                            save(e);
                            ins[2]++;
                        }
                    }
                }
            }
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new BusinessException("syncFromRawJson 解析异常: " + e.getMessage());
        }
        return String.format("sync: trade新%d/跳%d, nav新%d/跳%d, snap新%d, bs_leg新%d/跳%d", ins[0],
            skip[0], ins[1], skip[1], ins[2], ins[3], skip[3]);
    }

    private TzzbRecord base(String ledger, String type, LocalDateTime recordTime, JsonNode raw) {
        TzzbRecord e = new TzzbRecord();
        e.setLedger(ledger);
        e.setRecordType(type);
        e.setRecordTime(recordTime);
        @SuppressWarnings("unchecked") Map<String, Object> payload =
            OM.convertValue(raw, HashMap.class);
        e.setPayloadJson(payload);
        return e;
    }

    @Override
    public boolean hasNavDay(String ledger, LocalDate day) {
        return count(new LambdaQueryWrapper<TzzbRecord>().eq(TzzbRecord::getLedger, ledger)
            .eq(TzzbRecord::getRecordType, "nav_day")
            .eq(TzzbRecord::getRecordTime, day.atTime(15, 0))) > 0;
    }
}
