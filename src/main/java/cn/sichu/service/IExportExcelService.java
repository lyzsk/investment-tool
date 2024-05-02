package cn.sichu.service;

import cn.sichu.common.Resp;
import jakarta.servlet.http.HttpServletResponse;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public interface IExportExcelService {
    /**
     * 根据"resources/investment-template.xlsx"导出excel
     *
     * @param response response HTTP响应对象
     * @return cn.sichu.common.Resp<java.lang.String>
     * @author sichu huang
     * @date 2024/03/09
     **/
    Resp<String> exportInvestmentExcel(HttpServletResponse response);
}
