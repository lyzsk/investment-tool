package cn.sichu.paper.handler;

import cn.sichu.paper.service.IChainIngestService;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.DateTimeUtils;
import utils.StringUtils;

import java.time.LocalDate;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Component("chainIngestHandler")
@RequiredArgsConstructor
public class ChainIngestHandler implements JobHandler {
    private final IChainIngestService chainIngestService;

    /**
     * 链路入库补导(手动 runOnce): params 为空=全部历史目录按最终状态入库(slot=FINAL, 含 as-of);
     * params="skill LIVE|ASOF yyyyMMdd [slot]"=重导单个目录(slot 缺省 FINAL)
     *
     * @author sichu huang
     * @param params params
     * @since 2026/10/12
     * @return java.lang.String
     **/
    @Override
    public String execute(String params) throws Exception {
        if (StringUtils.isEmpty(params)) {
            return chainIngestService.ingestAll();
        }
        String[] p = params.trim().split("\\s+");
        if (p.length < 3) {
            throw new BusinessException("参数须为空或 'skill LIVE|ASOF yyyyMMdd [slot]', 实际: " + params);
        }
        return chainIngestService.ingest(p[0], p[1].toUpperCase(), LocalDate.parse(p[2], DateTimeUtils.YYYYMMDD),
            p.length > 3 ? p[3] : "FINAL", null, null, null);
    }
}
