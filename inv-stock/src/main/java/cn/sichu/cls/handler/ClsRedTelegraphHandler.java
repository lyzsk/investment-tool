package cn.sichu.cls.handler;

import cn.sichu.cls.service.IClsTelegraphService;
import cn.sichu.cls.service.IMarkdownFormatService;
import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.DateTimeUtils;
import utils.TradingDayUtils;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;

/**
 * @author sichu huang
 * @since 2026/01/14 14:15
 */
@Component("clsRedTelegraphHandler")
@RequiredArgsConstructor
public class ClsRedTelegraphHandler implements JobHandler {
    private final IClsTelegraphService clsTelegraphService;
    private final IMarkdownFormatService markdownFormatService;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) {
        /* 1. 抓取所有 level="B" 电报 */
        int count = clsTelegraphService.fetchAndSaveAllRedTelegraphs();
        /* 2. 确定目标日期: 如果是节假日/周末 -> 下一交易日 */
        LocalDate today = LocalDate.now();
        LocalDate targetDate =
            TradingDayUtils.isTradingDay(today) ? today : TradingDayUtils.getNextTradingDay(today);
        /* 3. 追加到目标日期的 Markdown */
        boolean success = clsTelegraphService.appendRedTelegraphs(targetDate);
        if (success) {
            String quarterDirName = DateTimeUtils.getQuarterStr(targetDate);
            Path dir = Paths.get(projectConfig.getMarkdown().getRootDir(), quarterDirName);
            String filename = targetDate.format(DateTimeUtils.YYYY_MM_DD) + ".md";
            Path markdownFile = dir.resolve(filename);
            boolean formatSuccess = markdownFormatService.formatMarkdownFile(markdownFile);
            if (!formatSuccess) {
                throw new BusinessException("格式化 Markdown 失败");
            }
        }
        return String.format("CLS 加红电报抓取完成: 新增 %d 条, 追加到 %s: %s", count, targetDate,
            success ? "成功" : "失败");
    }
}
