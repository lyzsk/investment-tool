package cn.sichu.reconcile.service.impl;

import cn.sichu.notify.service.INotifyService;
import cn.sichu.reconcile.entity.ReconcileResult;
import cn.sichu.reconcile.mapper.ReconcileResultMapper;
import cn.sichu.reconcile.service.IReconcileResultService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import utils.CollectionUtils;
import utils.DateTimeUtils;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Collectors;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Slf4j
@Service
@RequiredArgsConstructor
public class ReconcileResultServiceImpl extends ServiceImpl<ReconcileResultMapper, ReconcileResult>
    implements IReconcileResultService {
    public static final String OK = "OK";
    private static final int DETAIL_MAX = 1000;
    /* 一条推送最多列几项, 其余只给总数(微信消息别太长) */
    private static final int NOTIFY_MAX_LINES = 15;
    private final INotifyService notifyService;

    @Override
    public String newBatchNo(String bizType) {
        return LocalDateTime.now().format(DateTimeUtils.YYYYMMDDHHMMSS) + "_" + bizType;
    }

    @Override
    public ReconcileResult of(String batchNo, String bizType, String bizKey, String checkItem, Object expected,
        Object actual, String result, String detail) {
        ReconcileResult r = new ReconcileResult();
        r.setBatchNo(batchNo);
        r.setBizType(bizType);
        r.setBizKey(bizKey);
        r.setCheckItem(checkItem);
        r.setExpected(expected == null ? null : String.valueOf(expected));
        r.setActual(actual == null ? null : String.valueOf(actual));
        r.setResult(result);
        r.setDetail(detail == null || detail.length() <= DETAIL_MAX ? detail : detail.substring(0, DETAIL_MAX));
        return r;
    }

    @Override
    public String saveAndNotify(String title, List<ReconcileResult> rows) {
        if (CollectionUtils.isEmpty(rows)) {
            return title + ": 无检查项";
        }
        saveBatch(rows);
        List<ReconcileResult> bad = rows.stream().filter(r -> !OK.equals(r.getResult())).toList();
        Map<String, Long> counts = rows.stream()
            .collect(Collectors.groupingBy(ReconcileResult::getResult, TreeMap::new, Collectors.counting()));
        String summary = title + " 批次 " + rows.get(0).getBatchNo() + ": " + counts;
        if (bad.isEmpty()) {
            log.info(summary);
            return summary;
        }
        String lines = bad.stream().limit(NOTIFY_MAX_LINES)
            .map(r -> r.getBizKey() + " " + r.getCheckItem() + " " + r.getResult() + " 应" + r.getExpected() + "/实"
                + r.getActual() + (r.getDetail() == null ? "" : " " + r.getDetail()))
            .map(s -> s.length() > 160 ? s.substring(0, 160) + "…" : s).collect(Collectors.joining("\n"));
        log.warn("{}\n{}", summary, lines);
        notifyService.sendAsync("【对账】" + summary + "\n" + lines + (bad.size() > NOTIFY_MAX_LINES ?
            "\n…共 " + bad.size() + " 项" : ""));
        return summary;
    }
}
