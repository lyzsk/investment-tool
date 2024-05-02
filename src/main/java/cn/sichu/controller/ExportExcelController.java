package cn.sichu.controller;

import cn.sichu.annotation.LogAnnotation;
import cn.sichu.common.Resp;
import cn.sichu.service.IExportExcelService;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@RestController
@RequestMapping("/excel")
public class ExportExcelController {
    @Autowired
    IExportExcelService exportExcelService;

    // @Scheduled(cron = "30 0 0 * * *")
    @GetMapping("/export")
    @LogAnnotation(module = "ExportExcelController", operation = "exportInvestmentExcel")
    public Resp<String> exportInvestmentExcel(HttpServletResponse response) {
        return exportExcelService.exportInvestmentExcel(response);
    }
}
