package cn.sichu.controller;

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
    public Resp<String> getInvestmentTransactionStatementsExcel(HttpServletResponse response) {
        return exportExcelService.exportInvestmentExcel(response);
    }
}
