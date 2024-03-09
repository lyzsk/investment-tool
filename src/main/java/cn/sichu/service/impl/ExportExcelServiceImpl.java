package cn.sichu.service.impl;

import cn.sichu.domain.FundTransactionReportSheet;
import cn.sichu.domain.FundTransactionStatementSheet;
import cn.sichu.domain.GoldTransactionStatementSheet;
import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundTransaction;
import cn.sichu.service.IExportExcelService;
import com.alibaba.excel.EasyExcel;
import com.alibaba.excel.ExcelWriter;
import com.alibaba.excel.enums.WriteDirectionEnum;
import com.alibaba.excel.write.metadata.WriteSheet;
import com.alibaba.excel.write.metadata.fill.FillConfig;
import jakarta.servlet.http.HttpServletResponse;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Service
public class ExportExcelServiceImpl implements IExportExcelService {
    @Autowired
    private FundTransactionServiceImpl fundTransactionService;
    @Autowired
    private FundInformationServiceImpl fundInformationService;

    /**
     * 根据"resources/investment-template.xlsx"导出excel
     *
     * @param response response HTTP响应对象
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public void exportInvestmentExcel(HttpServletResponse response) throws IOException {
        response.setContentType("application/vnd.ms-excel; charset=UTF-8");
        response.setCharacterEncoding("utf-8");
        LocalDateTime localDateTime = LocalDateTime.now();
        String currentDateTime = localDateTime.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"));
        String fileName = URLEncoder.encode("-investment", StandardCharsets.UTF_8);
        response.setHeader("Content-Disposition",
            "attachment;filename*=UTF-8''" + currentDateTime + fileName + ".xlsx");

        String templatePath = "templates/";
        String template = "investment-template.xlsx";
        ClassPathResource classPathResource = new ClassPathResource(templatePath + template);
        InputStream inputStream = classPathResource.getInputStream();

        XSSFWorkbook workbook = new XSSFWorkbook(inputStream);
        workbook.setSheetName(0, "Fund Transaction Statement");
        workbook.setSheetName(1, "Fund Transaction Report");
        workbook.setSheetName(2, "Gold Transaction Statement");

        List<FundTransactionStatementSheet> fundTransactionStatementSheetDataList;
        List<FundTransactionReportSheet> fundTransactionReportSheetDataList = new ArrayList<>();
        List<GoldTransactionStatementSheet> goldTransactionStatementSheetDataList = new ArrayList<>();

        List<FundTransaction> fundTransactions = fundTransactionService.selectAllFundTransaction();
        fundTransactionStatementSheetDataList = initFundTransactionStatementSheet(fundTransactions);

        for (int i = 0; i < 10; i++) {
            FundTransactionReportSheet fundTransactionReportSheet =
                new FundTransactionReportSheet("270023", "广发全球精选股票", "04/03/2024", "06/03/2024", "", "2", "", "",
                    "广发基金管理有限公司", "中国银行");
            fundTransactionReportSheetDataList.add(fundTransactionReportSheet);
            GoldTransactionStatementSheet goldTransactionStatementSheet =
                new GoldTransactionStatementSheet("积存金", "04/03/2024", "04/03/2024", "04/03/2024", "492.20", "492.20",
                    "1.00", "1.00", "492.20", "492.20", "purchase", "中国银行");
            goldTransactionStatementSheetDataList.add(goldTransactionStatementSheet);
        }

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        workbook.write(outputStream);
        byte[] bytes = outputStream.toByteArray();
        inputStream = new ByteArrayInputStream(bytes);
        ExcelWriter writer = EasyExcel.write(response.getOutputStream()).withTemplate(inputStream).build();
        WriteSheet fundTransactionStatementSheetWriteSheet =
            EasyExcel.writerSheet("Fund Transaction Statement").build();
        WriteSheet fundTransactionReportSheetWriteSheet = EasyExcel.writerSheet("Fund Transaction Report").build();
        WriteSheet goldTransactionStatementSheetWriteSheet =
            EasyExcel.writerSheet("Gold Transaction Statement").build();

        FillConfig listFillConfig =
            FillConfig.builder().forceNewRow(true).direction(WriteDirectionEnum.VERTICAL).build();
        writer.fill(fundTransactionStatementSheetDataList, listFillConfig, fundTransactionStatementSheetWriteSheet);
        writer.fill(fundTransactionReportSheetDataList, listFillConfig, fundTransactionReportSheetWriteSheet);
        writer.fill(goldTransactionStatementSheetDataList, listFillConfig, goldTransactionStatementSheetWriteSheet);

        inputStream.close();
        writer.finish();
    }

    /**
     * @param fundTransactions fund_transaction 表中的全部数据List
     * @return java.util.List<cn.sichu.domain.FundTransactionStatementSheet>
     * @author sichu huang
     * @date 2024/03/09
     **/
    private List<FundTransactionStatementSheet> initFundTransactionStatementSheet(
        List<FundTransaction> fundTransactions) {
        List<FundTransactionStatementSheet> list = new ArrayList<>();
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy/MM/dd");

        for (FundTransaction transaction : fundTransactions) {
            String code = transaction.getCode();
            String shortName = transaction.getShortName();
            String applicationDate = sdf.format(transaction.getApplicationDate());
            String confirmationDate = sdf.format(transaction.getConfirmationDate());
            String settlementDate = sdf.format(transaction.getSettlementDate());
            String fee = transaction.getFee();
            String share = transaction.getShare();
            String nav = transaction.getNav();
            String amount = transaction.getAmount();
            String type = "";
            Integer rawType = transaction.getType();
            if (rawType == 0) {
                type = "purchase";
            } else if (rawType == 1) {
                type = "redemption";
            } else if (rawType == 2) {
                type = "dividend";
            }
            String fullName = "";
            String companyName = "";
            List<FundInformation> fundInformations = fundInformationService.selectFundInformationByCode(code);
            for (FundInformation fundInformation : fundInformations) {
                if (code.equals(fundInformation.getCode())) {
                    fullName = fundInformation.getFullName();
                    companyName = fundInformation.getCompanyName();
                }
            }
            String tradingPlatform = transaction.getTradingPlatform();

            FundTransactionStatementSheet fundTransactionStatementSheet =
                new FundTransactionStatementSheet(code, shortName, applicationDate, confirmationDate, settlementDate,
                    fee, "", share, "", nav, "", "", amount, "", type, fullName, companyName, tradingPlatform);
            list.add(fundTransactionStatementSheet);
        }
        return list;
    }
}
