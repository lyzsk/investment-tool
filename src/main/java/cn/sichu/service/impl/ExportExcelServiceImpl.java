package cn.sichu.service.impl;

import cn.sichu.domain.FundTransactionReportSheet;
import cn.sichu.domain.FundTransactionStatementSheet;
import cn.sichu.domain.GoldTransactionStatementSheet;
import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundPosition;
import cn.sichu.entity.FundTransaction;
import cn.sichu.enums.FundTransactionType;
import cn.sichu.exception.ExcelException;
import cn.sichu.mapper.FundTransactionReportSheetMapper;
import cn.sichu.mapper.FundTransactionStatementSheetMapper;
import cn.sichu.service.IExportExcelService;
import cn.sichu.utils.DateUtil;
import cn.sichu.utils.FinancialCalculationUtil;
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
import java.math.BigDecimal;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.DecimalFormat;
import java.text.ParseException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Objects;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Service
public class ExportExcelServiceImpl implements IExportExcelService {
    @Autowired
    FundTransactionStatementSheetMapper fundTransactionStatementSheetMapper;
    @Autowired
    FundTransactionReportSheetMapper fundTransactionReportSheetMapper;
    @Autowired
    FundHistoryNavServiceImpl fundHistoryNavService;

    /**
     * 根据"resources/investment-template.xlsx"导出excel
     *
     * @param response response HTTP响应对象
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public void exportInvestmentExcel(HttpServletResponse response) throws IOException, ParseException {
        response.setContentType("application/vnd.ms-excel; charset=UTF-8");
        response.setCharacterEncoding("utf-8");
        LocalDateTime localDateTime = LocalDateTime.now();
        String currentDateTime = localDateTime.format(DateTimeFormatter.ofPattern("yyyy-MM-dd"));
        String fileName = URLEncoder.encode("-investment", StandardCharsets.UTF_8);
        response.setHeader("Content-Disposition", "attachment;filename*=UTF-8''" + currentDateTime + fileName + ".xlsx");
        /* 配置template路径 */
        String templatePath = "templates/";
        String template = "investment-template.xlsx";
        ClassPathResource classPathResource = new ClassPathResource(templatePath + template);
        InputStream inputStream = classPathResource.getInputStream();
        /* 根据template创建需要导出的工作表, 以及设置工作簿 */
        XSSFWorkbook workbook = new XSSFWorkbook(inputStream);
        workbook.setSheetName(0, "Fund Transaction Statement");
        workbook.setSheetName(1, "Fund Transaction Report");
        workbook.setSheetName(2, "Gold Transaction Statement");
        /* 对list数据(一对多关系)进行处理 */
        List<FundTransaction> transactionList = fundTransactionStatementSheetMapper.selectAllFundTransaction();
        List<FundTransactionStatementSheet> fundTransactionStatementDataList = handleFundTransactionStatementSheetData(transactionList);
        List<FundPosition> positionList = fundTransactionReportSheetMapper.selectAllFundPositionByConditions();
        List<FundTransactionReportSheet> fundTransactionReportDataList = handleFundTransactionReportSheetData(positionList);
        List<GoldTransactionStatementSheet> goldTransactionStatementSheetDataList = new ArrayList<>();

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        workbook.write(outputStream);
        byte[] bytes = outputStream.toByteArray();
        inputStream = new ByteArrayInputStream(bytes);
        ExcelWriter writer = EasyExcel.write(response.getOutputStream()).withTemplate(inputStream).build();
        WriteSheet fundTransactionStatementWriteSheet = EasyExcel.writerSheet("Fund Transaction Statement").build();
        WriteSheet fundTransactionReportWriteSheet = EasyExcel.writerSheet("Fund Transaction Report").build();
        WriteSheet goldTransactionStatementWriteSheet = EasyExcel.writerSheet("Gold Transaction Statement").build();

        FillConfig listFillConfig = FillConfig.builder().forceNewRow(true).direction(WriteDirectionEnum.VERTICAL).build();
        writer.fill(fundTransactionStatementDataList, listFillConfig, fundTransactionStatementWriteSheet);
        writer.fill(fundTransactionReportDataList, listFillConfig, fundTransactionReportWriteSheet);
        writer.fill(goldTransactionStatementSheetDataList, listFillConfig, goldTransactionStatementWriteSheet);

        inputStream.close();
        writer.finish();
    }

    /**
     * 共20列: 1.code, 2.shortName, 3.applicationDate, 4.transactionDate, 5.confirmationDate, 6.settlementDate, 7.fee,
     * 8.totalFee, 9.share, 10.totalShare, 11.nav, 12.dilutedNav, 13.avgNavPerShare, 14.dividendAmountPerShare, 15.amount,
     * 16.totalAmount, 17.type, 18.tradingPlatform, 19.fullName, 20.companyName
     * <br/>
     * 其中14列可直接通过 `fund_transaction` && `fund_information` 设置, 6列需要通过 `fund_position` 查询和计算来设置;
     *
     * @param transactionList FundTransaction List
     * @return java.util.List<cn.sichu.domain.FundTransactionStatementSheet>
     * @author sichu huang
     * @date 2024/03/09
     **/
    private List<FundTransactionStatementSheet> handleFundTransactionStatementSheetData(List<FundTransaction> transactionList) {
        List<FundTransactionStatementSheet> list = new ArrayList<>();
        for (FundTransaction transaction : transactionList) {
            String code = transaction.getCode();
            List<FundInformation> fundInformationList = fundTransactionStatementSheetMapper.selectFundInformationByCode(code);
            if (fundInformationList.isEmpty()) {
                throw new ExcelException(999, "can't find fund_information data when setting 'Fund Transaction Statement' Sheet");
            }
            FundInformation information = fundInformationList.get(0);
            FundTransactionStatementSheet sheet = new FundTransactionStatementSheet();
            Date transactionDate = transaction.getTransactionDate();
            sheet.setCode(code);
            sheet.setApplicationDate(DateUtil.dateToStr(transaction.getApplicationDate()));
            sheet.setTransactionDate(DateUtil.dateToStr(transactionDate));
            sheet.setConfirmationDate(DateUtil.dateToStr(transaction.getConfirmationDate()));
            sheet.setSettlementDate(DateUtil.dateToStr(transaction.getSettlementDate()));
            sheet.setFee(String.valueOf(transaction.getFee()));
            sheet.setShare(String.valueOf(transaction.getShare()));
            sheet.setNav(String.valueOf(transaction.getNav()));
            sheet.setAmount(String.valueOf(transaction.getAmount()));
            sheet.setTradingPlatform(transaction.getTradingPlatform());
            sheet.setFullName(information.getFullName());
            sheet.setCompanyName(information.getCompanyName());
            Integer type = transaction.getType();
            if (Objects.equals(type, FundTransactionType.PURCHASE.getCode())) {
                sheet.setType(FundTransactionType.PURCHASE.getDescription());
                sheet.setDividendAmountPerShare("N/A");
                List<FundPosition> fundPositionList = fundTransactionStatementSheetMapper.selectFundPositionByConditions(code, transactionDate);
                /* PURCHASE_IN_TRAINSIT && CASH_DIVIDEND 不在 `fund_position` 中 */
                if (!fundPositionList.isEmpty()) {
                    for (FundPosition position : fundPositionList) {
                        BigDecimal totalFee = position.getTotalPurchaseFee();
                        BigDecimal heldShare = position.getHeldShare();
                        BigDecimal totalAmount = position.getTotalPrincipalAmount();
                        sheet.setTotalFee(String.valueOf(totalFee));
                        sheet.setTotalShare(String.valueOf(heldShare));
                        sheet.setTotalAmount(String.valueOf(totalAmount));
                        sheet.setDilutedNav(String.valueOf(FinancialCalculationUtil.calculateDilutedNav(totalAmount, totalFee, heldShare)));
                        sheet.setAvgNavPerShare(String.valueOf(FinancialCalculationUtil.calculateAvgNavPerShare(totalAmount, heldShare)));
                    }
                }
            } else if (Objects.equals(type, FundTransactionType.REDEMPTION.getCode())) {
                /* 赎回交易仅显示一条聚合数据 */
                sheet.setType(FundTransactionType.REDEMPTION.getDescription());
                sheet.setDividendAmountPerShare("N/A");
                sheet.setTotalFee(String.valueOf(transaction.getFee()));
                sheet.setTotalShare(String.valueOf(transaction.getShare()));
                sheet.setDilutedNav("N/A");
                sheet.setAvgNavPerShare("N/A");
                sheet.setTotalAmount(String.valueOf(transaction.getAmount()));
            } else if (Objects.equals(type, FundTransactionType.DIVIDEND.getCode())) {
                sheet.setType(FundTransactionType.DIVIDEND.getDescription());
                sheet.setTotalFee("N/A");
                sheet.setTotalShare(String.valueOf(transaction.getShare()));
                sheet.setDilutedNav("N/A");
                sheet.setAvgNavPerShare("N/A");
                sheet.setDividendAmountPerShare(String.valueOf(transaction.getDividendAmountPerShare()));
                sheet.setAmount(String.valueOf(transaction.getAmount()));
                // TODO: 分红的合计金额应该是根据mark进行累加计算, 即每一批次的交易(以赎回为分界)进行累加计算
                sheet.setTotalAmount(String.valueOf(transaction.getAmount()));
            }
            list.add(sheet);
        }
        return list;
    }

    /**
     * 共14列, 1.code, 2.shortName, 3.purchaseTransactionDate, 4.redemptionTransactionDate, 5.heldDays, 6.totalPrincipalAmount,
     * 7.totalAmount, 8.dividendCount, 9.totalDividendAmount, 10.profit, 11.dailyNavYield, 12.yieldRate, 13.tradingPlatform, 14.companyName
     * <br/>
     * 其中 7列直接设置, 2列通过 `fund_information` 查询设置, 5列通过 `fund_transaction` 查询和计算来设置
     *
     * @param positionList FundPosition List
     * @return java.util.List<cn.sichu.domain.FundTransactionReportSheet>
     * @author sichu huang
     * @date 2024/04/03
     **/
    private List<FundTransactionReportSheet> handleFundTransactionReportSheetData(List<FundPosition> positionList) throws ParseException {
        List<FundTransactionReportSheet> list = new ArrayList<>();
        for (FundPosition fundPosition : positionList) {
            String code = fundPosition.getCode();
            List<FundInformation> fundInformationList = fundTransactionReportSheetMapper.selectFundInformationByCode(code);
            if (fundInformationList.isEmpty()) {
                throw new ExcelException(999, "can't find fund_information data when setting 'Fund Transaction Report' Sheet");
            }
            FundInformation information = fundInformationList.get(0);
            FundTransactionReportSheet sheet = new FundTransactionReportSheet();
            sheet.setCode(code);
            sheet.setShortName(information.getShortName());
            sheet.setCompanyName(information.getCompanyName());
            sheet.setTradingPlatform(fundPosition.getTradingPlatform());
            sheet.setPurchaseTransactionDate(String.valueOf(fundPosition.getTransactionDate()));
            sheet.setRedemptionTransactionDate(String.valueOf(fundPosition.getRedemptionDate()));
            Integer heldDays = fundPosition.getHeldDays();
            sheet.setHeldDays(String.valueOf(heldDays));
            BigDecimal totalPrincipalAmount = fundPosition.getTotalPrincipalAmount();
            sheet.setTotalPrincipalAmount(String.valueOf(totalPrincipalAmount));
            BigDecimal totalAmount = fundPosition.getTotalAmount();
            sheet.setTotalAmount(String.valueOf(totalAmount));
            int dividendCount = 0;
            BigDecimal totalDividendAmount = BigDecimal.ZERO;
            BigDecimal profit = BigDecimal.ZERO;
            String[] splits = fundPosition.getMark().split("->");
            List<FundTransaction> divdendTransactionList =
                fundTransactionReportSheetMapper.selectAllDividendTransactionByConditions(DateUtil.strToDate(splits[0]),
                    DateUtil.strToDate(splits[1]), FundTransactionType.DIVIDEND.getCode());
            dividendCount += divdendTransactionList.size();
            sheet.setDividendCount(String.valueOf(dividendCount));
            for (FundTransaction transaction : divdendTransactionList) {
                totalDividendAmount = totalDividendAmount.add(transaction.getAmount());
            }
            sheet.setTotalDividendAmount(String.valueOf(totalDividendAmount));
            profit = profit.add(totalDividendAmount).add(fundPosition.getTotalAmount());
            sheet.setProfit(String.valueOf(profit));
            sheet.setDailyNavYield(String.valueOf(FinancialCalculationUtil.calculateDailyNavYield(profit, heldDays)));
            BigDecimal yieldRate = FinancialCalculationUtil.calculateYieldRate(profit, totalPrincipalAmount);
            String yieldRateStr = new DecimalFormat("0.00%").format(yieldRate);
            sheet.setYieldRate(yieldRateStr);
            list.add(sheet);
        }
        return list;
    }

}
