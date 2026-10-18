package cn.sichu.paper.controller;

import cn.sichu.paper.service.IChainIngestService;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import result.Result;
import utils.DateTimeUtils;

import java.time.LocalDate;

/**
 * 链路入库入口(10/16 晚: check md 直接起的 07 复盘不经 Java handler, 跑完由 check md 调本接口入库)
 *
 * @author sichu huang
 * @since 2026/10/16 20:45
 */
@RestController
@RequestMapping("/api/paper/chain")
@RequiredArgsConstructor
public class ChainIngestController {
    private final IChainIngestService chainIngestService;

    /**
     * 单个运行目录入库 results/&lt;skill&gt;_chain/&lt;live|asof&gt;-&lt;date&gt;
     * 例: curl -X POST "localhost:8888/api/paper/chain/ingest?skill=xingjianye&amp;mode=LIVE&amp;date=20261016&amp;slot=review&amp;exitCode=0"
     *
     * @param skill skill
     * @param mode LIVE / ASOF
     * @param date yyyyMMdd
     * @param slot HHMM / review / FINAL
     * @param exitCode driver 退出码, 不知道传空
     * @return result.Result<java.lang.String>
     * @author sichu huang
     * @since 2026/10/16 20:45:00
     */
    @PostMapping("/ingest")
    public Result<String> ingest(@RequestParam String skill, @RequestParam(defaultValue = "LIVE") String mode,
        @RequestParam String date, @RequestParam(defaultValue = "review") String slot,
        @RequestParam(required = false) Integer exitCode) {
        try {
            return Result.success(
                chainIngestService.ingest(skill, mode.toUpperCase(), LocalDate.parse(date, DateTimeUtils.YYYYMMDD),
                    slot, exitCode, null, null));
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new BusinessException("链路入库失败 " + skill + " " + mode + " " + date + " " + slot + ": " + e.getMessage());
        }
    }
}
