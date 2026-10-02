package cn.sichu.tzzb.controller;

import cn.sichu.tzzb.service.ITzzbRecordService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import result.Result;

/**
 *
 * @author sichu huang
 * @since 2026/10/01 23:53
 */
@RestController
@RequestMapping("/api/cb/tzzb")
@RequiredArgsConstructor
public class TzzbRecordController {
    private final ITzzbRecordService tzzbRecordService;

    /**
     * 手动触发 downloads/tzzb/<ledger>/*.json 同步入库
     * 例: curl -X POST "localhost:8888/api/cb/tzzb/sync?ledger=bchitudou0"
     *
     * @param ledger ledger
     * @return result.Result<java.lang.String>
     * @author sichu huang
     * @since 2026/10/01 23:53:39
     */
    @PostMapping("/sync")
    public Result<String> sync(@RequestParam(defaultValue = "bchitudou0") String ledger) {
        return Result.success(tzzbRecordService.syncFromRawJson(ledger));
    }
}
