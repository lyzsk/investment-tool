package cn.sichu.service;

import jakarta.servlet.http.HttpServletResponse;

import java.io.IOException;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IExportExcelService {
    /**
     * 根据"resources/investment-template.xlsx"导出excel
     *
     * @param response response HTTP响应对象
     * @author sichu huang
     * @date 2024/03/09
     **/
    void exportInvestmentExcel(HttpServletResponse response) throws IOException;
}
