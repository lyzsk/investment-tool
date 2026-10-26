package cn.sichu.kline.controller;

import cn.sichu.kline.service.IKlineInboxService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import result.Result;

import java.util.List;

/**
 * K 线 / 分时 / 涨停截图收件箱(原图 downloads/kline/yyyy.MM.dd/, 产物和核销状态 results/kline/)
 *
 * @author sichu huang
 * @since 2026/10/25
 */
@RestController
@RequestMapping("/api/kline")
@RequiredArgsConstructor
public class KlineInboxController {
    private final IKlineInboxService klineInboxService;

    /**
     * 批量上传截图(只存原图, 不分析; 每晚 check md 自动收件, 想马上看再调 /process)
     * <br/>
     * form-data: files[] + date(yyyy.MM.dd, 可空 = 今天)
     *
     * @param files 截图
     * @param date  yyyy.MM.dd
     * @return result.Result<java.lang.String> "存入 x/跳过 y → 目录"
     * @author sichu huang
     * @since 2026/10/25
     */
    @PostMapping("/upload")
    public Result<String> upload(@RequestParam("files") List<MultipartFile> files,
        @RequestParam(value = "date", required = false) String date) {
        return Result.success(klineInboxService.upload(files, date));
    }

    /**
     * 立刻跑收件箱(非交易日 / 盘中二次确认): OCR 收件 → 续画未来 3 日 → 导师核销 → 到期对答案
     *
     * @param date  yyyy.MM.dd, 可空 = 全部有新图 / 没核销完的日子
     * @param force true = 盘中也跑 OCR
     * @return result.Result<java.lang.String> 各图核销状态
     * @author sichu huang
     * @since 2026/10/25
     */
    @PostMapping("/process")
    public Result<String> process(@RequestParam(value = "date", required = false) String date,
        @RequestParam(value = "force", required = false, defaultValue = "false") boolean force) throws Exception {
        return Result.success(klineInboxService.process(date, force));
    }
}
