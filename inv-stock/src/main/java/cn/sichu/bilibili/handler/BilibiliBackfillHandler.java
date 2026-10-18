package cn.sichu.bilibili.handler;

import cn.sichu.bilibili.service.IBilibiliReconcileService;
import cn.sichu.bilibili.service.IBilibiliVideoService;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.StringUtils;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Component("bilibiliBackfillHandler")
@RequiredArgsConstructor
public class BilibiliBackfillHandler implements JobHandler {
    private final IBilibiliReconcileService bilibiliReconcileService;
    private final IBilibiliVideoService bilibiliVideoService;

    /**
     * UP 视频补跑(§5.4: 历史补跑并入 bilibili_video 状态机, 替代 backfill_bilibili.py 的逐视频下载/处理):
     * params: --up taoge|qushitiange|lubenyuan [--enqueue N --from yyyy-MM-dd --to yyyy-MM-dd] [--process N(默认 2)]
     * ① --enqueue N: 从视频索引登记最多 N 条 NEW 行(origin=BACKFILL) ② 本轮下载+处理最多 N 条 BACKFILL 行(复用每日任务的认领制+显存闸)
     * sum/distill 仍由 backfill_bilibili.py --llm-batch 按天做, 对账任务再把 DB 推进到 SUMMARIZED/DISTILLED
     *
     * @author sichu huang
     * @param params params
     * @since 2026/10/12
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        Map<String, String> opt = parse(params);
        String up = opt.get("up");
        if (StringUtils.isEmpty(up)) {
            throw new BusinessException("缺 --up(taoge/qushitiange/lubenyuan), 实际参数: " + params);
        }
        String mid = bilibiliReconcileService.midOf(up);
        StringBuilder sb = new StringBuilder();
        int enqueue = Integer.parseInt(opt.getOrDefault("enqueue", "0"));
        if (enqueue > 0) {
            sb.append(bilibiliReconcileService.enqueueBackfill(up, date(opt.get("from")), date(opt.get("to")), enqueue))
                .append("; ");
        }
        int process = Integer.parseInt(opt.getOrDefault("process", "2"));
        sb.append(bilibiliVideoService.downloadPendingVideos(3, mid, IBilibiliVideoService.ORIGIN_BACKFILL, process))
            .append("; ")
            .append(bilibiliVideoService.processPendingVideos(3, mid, IBilibiliVideoService.ORIGIN_BACKFILL, process));
        return "B站补跑 " + up + ": " + sb;
    }

    private Map<String, String> parse(String params) {
        Map<String, String> opt = new HashMap<>();
        if (StringUtils.isEmpty(params)) {
            return opt;
        }
        String[] parts = params.trim().split("\\s+");
        for (int i = 0; i < parts.length - 1; i++) {
            if (parts[i].startsWith("--")) {
                opt.put(parts[i].substring(2), parts[i + 1]);
            }
        }
        return opt;
    }

    private LocalDate date(String s) {
        return StringUtils.isEmpty(s) ? null : LocalDate.parse(s);
    }
}
