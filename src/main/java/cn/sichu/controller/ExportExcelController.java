package cn.sichu.controller;

import cn.sichu.service.IExportExcelService;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@RestController
@RequestMapping("/excel")
public class ExportExcelController {
    @Autowired
    private IExportExcelService exportExcelService;

    @GetMapping("/export")
    public void getInvestmentTransactionStatementsExcel(HttpServletResponse response) throws IOException {
        exportExcelService.exportInvestmentExcel(response);
    }
}
