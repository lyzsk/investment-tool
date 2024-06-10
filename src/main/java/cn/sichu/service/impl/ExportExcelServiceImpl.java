package cn.sichu.service.impl;

import cn.sichu.domain.FundTransactionReportSheet;
import cn.sichu.domain.FundTransactionStatementSheet;
import cn.sichu.domain.GoldTransactionSummarySheet;
import cn.sichu.entity.*;
import cn.sichu.enums.AppExceptionCodeMsg;
import cn.sichu.enums.FundTransactionType;
import cn.sichu.enums.GoldTransactionType;
import cn.sichu.exception.ExcelException;
import cn.sichu.mapper.FundTransactionReportSheetMapper;
import cn.sichu.mapper.FundTransactionStatementSheetMapper;
import cn.sichu.mapper.GoldTransactionSummarySheetMapper;
import cn.sichu.service.IExportExcelService;
import cn.sichu.utils.DateTimeUtil;
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
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

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
    GoldTransactionSummarySheetMapper goldTransactionSummarySheetMapper;

    @Override
    public void exportInvestmentExcel(HttpServletResponse response) throws IOException {
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
        workbook.setSheetName(2, "Gold Transaction Summary");
        /* 对list数据(一对多关系)进行处理 */
        List<FundTransaction> fundTransactionList = fundTransactionStatementSheetMapper.selectAllFundTransaction();
        List<FundTransactionStatementSheet> fundTransactionStatementDataList = handleFundTransactionStatementSheetData(fundTransactionList);
        List<FundPosition> fundPositionList = fundTransactionReportSheetMapper.selectAllFundPosition();
        List<FundTransactionReportSheet> fundTransactionReportDataList = new ArrayList<>();
        Map<String, String> fundTransactionReportDataMap = new HashMap<>();
        handleFundTransactionReportSheetData(fundPositionList, fundTransactionReportDataList, fundTransactionReportDataMap);
        List<GoldTransaction> goldTransactionList = goldTransactionSummarySheetMapper.selectAllGoldTransaction();
        List<GoldPosition> goldPositionList = goldTransactionSummarySheetMapper.selectAllGoldPosition();
        List<GoldTransactionSummarySheet> goldTransactionSummaryDataList = new ArrayList<>();
        Map<String, String> goldTransactionSummaryDataMap = new HashMap<>();
        handleGoldTransactionSummarySheetData(goldTransactionList, goldPositionList, goldTransactionSummaryDataList,
            goldTransactionSummaryDataMap);

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        workbook.write(outputStream);
        byte[] bytes = outputStream.toByteArray();
        inputStream = new ByteArrayInputStream(bytes);
        ExcelWriter writer = EasyExcel.write(response.getOutputStream()).withTemplate(inputStream).build();
        WriteSheet sheet0 = EasyExcel.writerSheet("Fund Transaction Statement").build();
        WriteSheet sheet1 = EasyExcel.writerSheet("Fund Transaction Report").build();
        WriteSheet sheet2 = EasyExcel.writerSheet("Gold Transaction Summary").build();

        FillConfig fillConfig = FillConfig.builder().forceNewRow(true).direction(WriteDirectionEnum.VERTICAL).build();
        writer.fill(fundTransactionStatementDataList, fillConfig, sheet0);
        writer.fill(fundTransactionReportDataList, fillConfig, sheet1);
        writer.fill(fundTransactionReportDataMap, fillConfig, sheet1);
        writer.fill(goldTransactionSummaryDataList, fillConfig, sheet2);
        writer.fill(goldTransactionSummaryDataMap, fillConfig, sheet2);

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
                throw new ExcelException(AppExceptionCodeMsg.EXCEL_EXPORT_EXCEPTION.getCode(),
                    "can't find fund_information data when setting 'Fund Transaction Statement' Sheet");
            }
            FundInformation information = fundInformationList.get(0);
            FundTransactionStatementSheet sheet = new FundTransactionStatementSheet();
            Date transactionDate = transaction.getTransactionDate();
            sheet.setCode(code);
            sheet.setShortName(information.getShortName());
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
     * @param list         FundTransactionReportSheet 一对多关系数据(List)
     * @param map          FundTransactionReportSheet 一对一关系数据数据(HashMap)
     * @author sichu huang
     * @date 2024/04/03
     **/
    private void handleFundTransactionReportSheetData(List<FundPosition> positionList, List<FundTransactionReportSheet> list,
        Map<String, String> map) {
        BigDecimal sumTotalPrincipalAmount = BigDecimal.ZERO;
        BigDecimal sumTotalAmount = BigDecimal.ZERO;
        int sumDividendCount = 0;
        BigDecimal sumTotalDividendAmount = BigDecimal.ZERO;
        BigDecimal sumProfit = BigDecimal.ZERO;
        BigDecimal sumDailyNavYield = BigDecimal.ZERO;
        DecimalFormat decimalFormat = new DecimalFormat("0.00%");
        for (FundPosition fundPosition : positionList) {
            String code = fundPosition.getCode();
            List<FundInformation> fundInformationList = fundTransactionReportSheetMapper.selectFundInformationByCode(code);
            if (fundInformationList.isEmpty()) {
                throw new ExcelException(AppExceptionCodeMsg.EXCEL_EXPORT_EXCEPTION.getCode(),
                    "can't find fund_information data when setting 'Fund Transaction Report' Sheet");
            }
            FundInformation information = fundInformationList.get(0);
            FundTransactionReportSheet sheet = new FundTransactionReportSheet();
            sheet.setCode(code);
            sheet.setShortName(information.getShortName());
            sheet.setCompanyName(information.getCompanyName());
            sheet.setTradingPlatform(fundPosition.getTradingPlatform());
            Date startDate = fundPosition.getTransactionDate();
            sheet.setPurchaseTransactionDate(DateUtil.dateToStr(startDate));
            Date endDate = fundPosition.getRedemptionDate();
            sheet.setRedemptionTransactionDate(endDate == null ? "" : DateUtil.dateToStr(endDate));
            Integer heldDays = fundPosition.getHeldDays();
            if (heldDays == 0) {
                throw new ExcelException(AppExceptionCodeMsg.EXCEL_EXPORT_EXCEPTION.getCode(),
                    "please update status first before exporting excel, because held days can't be 0");
            }
            sheet.setHeldDays(String.valueOf(heldDays));
            BigDecimal totalPrincipalAmount = fundPosition.getTotalPrincipalAmount();
            sheet.setTotalPrincipalAmount(String.valueOf(totalPrincipalAmount));
            sumTotalPrincipalAmount = sumTotalPrincipalAmount.add(totalPrincipalAmount);
            BigDecimal totalAmount = fundPosition.getTotalAmount();
            sheet.setTotalAmount(String.valueOf(totalAmount));
            sumTotalAmount = sumTotalAmount.add(totalAmount);
            int dividendCount = 0;
            BigDecimal totalDividendAmount = BigDecimal.ZERO;
            BigDecimal profit = BigDecimal.ZERO;
            String mark = fundPosition.getMark();
            List<FundTransaction> divdendTransactionList;
            if (mark != null && !mark.equals("")) {
                divdendTransactionList = fundTransactionReportSheetMapper.selectAllDividendTransactionByConditions(startDate, endDate,
                    FundTransactionType.DIVIDEND.getCode());
            } else {
                divdendTransactionList =
                    fundTransactionReportSheetMapper.selectAllDividendTransactionByConditions(startDate, fundPosition.getUpdateDate(),
                        FundTransactionType.DIVIDEND.getCode());
            }
            dividendCount += divdendTransactionList.size();
            sheet.setDividendCount(String.valueOf(dividendCount));
            sumDividendCount += dividendCount;
            for (FundTransaction transaction : divdendTransactionList) {
                totalDividendAmount = totalDividendAmount.add(transaction.getAmount());
            }
            sheet.setTotalDividendAmount(totalDividendAmount.equals(BigDecimal.ZERO) ? "0.00" : String.valueOf(totalDividendAmount));
            sumTotalDividendAmount = sumTotalDividendAmount.add(totalDividendAmount);
            profit = profit.add(fundPosition.getTotalAmount()).add(totalDividendAmount).subtract(fundPosition.getTotalPrincipalAmount());
            sheet.setProfit(String.valueOf(profit));
            sumProfit = sumProfit.add(profit);
            BigDecimal dailyNavYield = FinancialCalculationUtil.calculateDailyNavYield(profit, heldDays);
            sheet.setDailyNavYield(String.valueOf(dailyNavYield));
            sumDailyNavYield = sumDailyNavYield.add(dailyNavYield);
            BigDecimal yieldRate = FinancialCalculationUtil.calculateYieldRate(profit, totalPrincipalAmount);
            sheet.setYieldRate(decimalFormat.format(yieldRate));
            list.add(sheet);
        }
        map.put("sumTotalPrincipalAmount", String.valueOf(sumTotalPrincipalAmount));
        map.put("sumTotalAmount", String.valueOf(sumTotalAmount));
        map.put("sumDividendCount", String.valueOf(sumDividendCount));
        map.put("sumTotalDividendAmount", sumTotalDividendAmount.equals(BigDecimal.ZERO) ? "0.00" : String.valueOf(sumTotalDividendAmount));
        map.put("sumProfit", String.valueOf(sumProfit));
        if (sumTotalPrincipalAmount.equals(BigDecimal.ZERO)) {
            map.put("totalYieldRate", "0.00%");
        } else {
            map.put("totalYieldRate", decimalFormat.format(
                FinancialCalculationUtil.calculateYieldRate(sumTotalAmount.subtract(sumTotalPrincipalAmount), sumTotalPrincipalAmount)));
        }
    }

    /**
     * @param transactionList GoldTransaction List
     * @param positionList    GoldPosition List
     * @param list            一对多关系数据(List)
     * @param map             一对一关系数据数据(HashMap)
     * @author sichu huang
     * @date 2024/06/11
     **/
    private void handleGoldTransactionSummarySheetData(List<GoldTransaction> transactionList, List<GoldPosition> positionList,
        List<GoldTransactionSummarySheet> list, Map<String, String> map) {
        BigDecimal sumPrincipalAmount = BigDecimal.ZERO;
        BigDecimal sumGrams = BigDecimal.ZERO;
        BigDecimal sumAmount = BigDecimal.ZERO;
        BigDecimal sumProfit = BigDecimal.ZERO;
        /* 一对多关系数据(List) */
        for (GoldTransaction transaction : transactionList) {
            GoldTransactionSummarySheet sheet = new GoldTransactionSummarySheet();
            BigDecimal grams = transaction.getGrams();
            sheet.setGrams(String.valueOf(grams));
            BigDecimal pricePerGram = transaction.getPricePerGram();
            sheet.setPricePerGram(String.valueOf(pricePerGram));
            BigDecimal amount = FinancialCalculationUtil.calculateGoldTransactionAmount(grams, pricePerGram);
            sheet.setAmount(String.valueOf(amount));
            if (transaction.getType().equals(GoldTransactionType.PURCHASE.getCode())) {
                sheet.setType(GoldTransactionType.PURCHASE.getDescription());
                sheet.setPurchaseTime(DateTimeUtil.localDateTimeToDateStr(transaction.getTransactionTime()));
                sumGrams = sumGrams.add(grams);
                sumAmount = sumAmount.add(amount);
            } else {
                sheet.setType(GoldTransactionType.REDEMPTION.getDescription());
                sheet.setRedemptionTime(DateTimeUtil.localDateTimeToDateStr(transaction.getTransactionTime()));
                sumGrams = sumGrams.subtract(grams);
                sumAmount = sumAmount.subtract(amount);
            }
            sheet.setTradingPlatform(transaction.getTradingPlatform());
            list.add(sheet);
        }
        /* 一对一关系数据数据(HashMap) */
        for (GoldPosition position : positionList) {
            if (position.getMark() == null || position.getMark().equals("")) {
                continue;
            }
            BigDecimal profit = position.getTotalAmount().subtract(position.getTotalPrincipalAmount());
            sumProfit = sumProfit.add(profit);
        }
        DecimalFormat decimalFormat = new DecimalFormat("0.00%");
        map.put("sumPrincipalAmount", String.valueOf(sumPrincipalAmount));
        map.put("sumGrams", String.valueOf(sumGrams));
        map.put("sumAmount", String.valueOf(sumAmount));
        map.put("sumProfit", String.valueOf(sumProfit));
        BigDecimal yieldRate = FinancialCalculationUtil.calculateYieldRate(sumProfit, sumPrincipalAmount);
        map.put("sumYieldRate", decimalFormat.format(yieldRate));
        map.put("avgAmountPerGram", String.valueOf(FinancialCalculationUtil.calculateAvgPricePerGram(sumAmount, sumGrams)));
    }
}
