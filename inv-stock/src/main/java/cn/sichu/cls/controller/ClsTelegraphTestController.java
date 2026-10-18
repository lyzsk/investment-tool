package cn.sichu.cls.controller;

import cn.sichu.cls.service.IClsTelegraphService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * @author sichu huang
 * @since 2026/01/03 17:00
 */

@RestController
@RequestMapping("/api/cls")
@RequiredArgsConstructor
@Slf4j
public class ClsTelegraphTestController {
    private final IClsTelegraphService clsTelegraphService;

    @PostMapping("/fetch-and-save")
    public String fetchAndSaveLatestTelegraphs() {
        // clsTelegraphService.fetchAndSaveLatestTelegraphs();
        return "CLS 电报拉取任务已执行，请查看日志或数据库";
    }
}
