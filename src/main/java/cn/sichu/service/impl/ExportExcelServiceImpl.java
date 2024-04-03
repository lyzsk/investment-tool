package cn.sichu.service.impl;

import cn.sichu.domain.FundTransactionReportSheet;
import cn.sichu.domain.FundTransactionStatementSheet;
import cn.sichu.domain.GoldTransactionStatementSheet;
import cn.sichu.entity.FundHistoryPosition;
import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundPosition;
import cn.sichu.entity.FundTransaction;
import cn.sichu.enums.FundTransactionType;
import cn.sichu.exception.ExcelException;
import cn.sichu.mapper.FundTransactionStatementSheetMapper;
import cn.sichu.service.IExportExcelService;
import cn.sichu.utils.DateUtil;
import cn.sichu.utils.FinancialCalculationUtil;
import cn.sichu.utils.TransactionDayUtil;
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
import java.math.RoundingMode;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.ParseException;
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
    FundHistoryNavServiceImpl fundHistoryNavService;

    private PriorityQueue<FundTransactionStatementSheet> pq = new PriorityQueue<>((o1, o2) -> {
        int cc = o1.getCode().compareTo(o2.getCode());
        if (cc != 0) {
            return o2.getTransactionDate().compareTo(o1.getTransactionDate());
        }
        return cc;
    });
    private Map<Integer, PriorityQueue<FundTransactionStatementSheet>> map = new HashMap<>();
    private int index = 0;

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

        String templatePath = "templates/";
        String template = "investment-template.xlsx";
        ClassPathResource classPathResource = new ClassPathResource(templatePath + template);
        InputStream inputStream = classPathResource.getInputStream();

        XSSFWorkbook workbook = new XSSFWorkbook(inputStream);
        workbook.setSheetName(0, "Fund Transaction Statement");
        workbook.setSheetName(1, "Fund Transaction Report");
        workbook.setSheetName(2, "Gold Transaction Statement");

        List<FundTransaction> fundTransactionList = fundTransactionStatementSheetMapper.selectAllFundTransaction();
        List<FundTransactionStatementSheet> fundTransactionStatementSheetDataList = setFundTransactionStatementSheetData(fundTransactionList);
        List<FundTransactionReportSheet> fundTransactionReportSheetDataList =
            setfundTransactionReportSheetData(fundTransactionStatementSheetDataList);
        List<GoldTransactionStatementSheet> goldTransactionStatementSheetDataList = new ArrayList<>();

        for (int i = 0; i < 10; i++) {
            GoldTransactionStatementSheet goldTransactionStatementSheet =
                new GoldTransactionStatementSheet("积存金", "04/03/2024", "04/03/2024", "04/03/2024", "492.20", "492.20", "1.00", "1.00", "492.20",
                    "492.20", "purchase", "中国银行");
            goldTransactionStatementSheetDataList.add(goldTransactionStatementSheet);
        }

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        workbook.write(outputStream);
        byte[] bytes = outputStream.toByteArray();
        inputStream = new ByteArrayInputStream(bytes);
        ExcelWriter writer = EasyExcel.write(response.getOutputStream()).withTemplate(inputStream).build();
        WriteSheet fundTransactionStatementSheetWriteSheet = EasyExcel.writerSheet("Fund Transaction Statement").build();
        WriteSheet fundTransactionReportSheetWriteSheet = EasyExcel.writerSheet("Fund Transaction Report").build();
        WriteSheet goldTransactionStatementSheetWriteSheet = EasyExcel.writerSheet("Gold Transaction Statement").build();

        FillConfig listFillConfig = FillConfig.builder().forceNewRow(true).direction(WriteDirectionEnum.VERTICAL).build();
        writer.fill(fundTransactionStatementSheetDataList, listFillConfig, fundTransactionStatementSheetWriteSheet);
        writer.fill(fundTransactionReportSheetDataList, listFillConfig, fundTransactionReportSheetWriteSheet);
        writer.fill(goldTransactionStatementSheetDataList, listFillConfig, goldTransactionStatementSheetWriteSheet);

        inputStream.close();
        writer.finish();
    }

    /**
     * @param fundTransactions FundTransaction List
     * @return java.util.List<cn.sichu.domain.FundTransactionStatementSheet>
     * @author sichu huang
     * @date 2024/03/09
     **/
    private List<FundTransactionStatementSheet> setFundTransactionStatementSheetData(List<FundTransaction> fundTransactions) {
        List<FundTransactionStatementSheet> list = new ArrayList<>();
        for (FundTransaction fundTransaction : fundTransactions) {
            String code = fundTransaction.getCode();
            Integer type = fundTransaction.getType();
            List<FundInformation> fundInformationList = fundTransactionStatementSheetMapper.selectFundInformationByCode(code);
            if (fundInformationList.isEmpty()) {
                throw new ExcelException(999, "获取基金信息失败");
            }
            FundInformation fundInformation = fundInformationList.get(0);
            FundTransactionStatementSheet fundTransactionStatementSheet = new FundTransactionStatementSheet();
            handleFundTransactionStatementSheetData(fundTransactionStatementSheet, fundTransaction, fundInformation, type);
            list.add(fundTransactionStatementSheet);
        }
        return list;
    }

    /**
     * set data into template sheet: A.code, B.shortName, C.applicationDate, D.transactionDate, E.confirmationDate, F.settlementDate, G.fee,
     * <b>H.totalFee(optional),</b> I.share, <b>J.totalShare(optional),</b> K.nav, <b>L.dilutedNav(optional),</b> <b>M.avgNavPerShare(optional),</b>
     * N.amount, <b>O.totalAmount(optional),</b> P.type, Q.tradingPlatform, R.fullName, S.companyName
     * 合计 19 列
     *
     * @param sheet       FundTransactionStatementSheet
     * @param transaction FundTransaction
     * @param information FundInformation
     * @param type        type
     * @author sichu huang
     * @date 2024/04/01
     **/
    private void handleFundTransactionStatementSheetData(FundTransactionStatementSheet sheet, FundTransaction transaction,
        FundInformation information, Integer type) {
        /* set A, B, C, D, E, F, G, I, K, N, Q, R, S (13列) */
        String code = transaction.getCode();
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
        /* set P */
        if (Objects.equals(type, FundTransactionType.PURCHASE.getCode())) {
            sheet.setType(FundTransactionType.PURCHASE.getDescription());
            /* set H, J, L, M, O */
            List<FundPosition> fundPositionList = fundTransactionStatementSheetMapper.selectFundPositionByConditions(code, transactionDate);
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
            } else {
                List<FundHistoryPosition> fundHistoryPositionList =
                    fundTransactionStatementSheetMapper.selectFundHistoryPositionByConditions(code, transactionDate);
                if (!fundHistoryPositionList.isEmpty()) {
                    for (FundHistoryPosition position : fundHistoryPositionList) {
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
            }
            pq.add(sheet);
            map.put(index++, pq);
        } else if (Objects.equals(type, FundTransactionType.REDEMPTION.getCode())) {
            /* if REDEMPTION, set H, J, L, M, O */
            sheet.setType(FundTransactionType.REDEMPTION.getDescription());
            sheet.setTotalFee(String.valueOf(transaction.getFee()));
            sheet.setTotalShare(String.valueOf(transaction.getShare()));
            sheet.setDilutedNav("N/A");
            sheet.setAvgNavPerShare("N/A");
            sheet.setTotalAmount(String.valueOf(transaction.getAmount()));
            pq.add(sheet);
            map.put(index++, pq);
        } else if (Objects.equals(type, FundTransactionType.DIVIDEND.getCode())) {
            /* if DIVIDEND, set H, J, L, M, O */
            sheet.setType(FundTransactionType.DIVIDEND.getDescription());
            sheet.setTotalFee(String.valueOf(transaction.getFee()));
            sheet.setTotalShare(String.valueOf(transaction.getShare()));
            sheet.setDilutedNav("N/A");
            sheet.setAvgNavPerShare("N/A");
            sheet.setTotalAmount(String.valueOf(transaction.getAmount()));
        }
    }

    /**
     * TODO: 实现了, 但是heldDays, 赎回交易待优化
     *
     * @param statementSheetList FundTransactionReportSheet List
     * @return java.util.List<cn.sichu.domain.FundTransactionReportSheet>
     * @author sichu huang
     * @date 2024/04/03
     **/
    private List<FundTransactionReportSheet> setfundTransactionReportSheetData(List<FundTransactionStatementSheet> statementSheetList)
        throws ParseException, IOException {
        List<FundTransactionReportSheet> list = new ArrayList<>();
        Map<String, FundTransactionStatementSheet> lastTransactionMap = new TreeMap<>(String::compareTo);
        for (FundTransactionStatementSheet statementSheet : statementSheetList) {
            String code = statementSheet.getCode();
            lastTransactionMap.put(code, statementSheet);
        }
        for (FundTransactionStatementSheet lastTransaction : lastTransactionMap.values()) {
            FundTransactionReportSheet sheet = new FundTransactionReportSheet();
            String code = lastTransaction.getCode();
            Date formattedDate = DateUtil.formatDate(new Date());
            sheet.setCode(code);
            sheet.setShortName(lastTransaction.getShortName());
            String transactionDate = lastTransaction.getTransactionDate();
            String redemptionDate = "N/A";
            String dividendDate = "N/A";
            Date firstPurchaseDate = getFirstPurchaseDate(code, statementSheetList);
            if (firstPurchaseDate == null) {
                throw new ExcelException(999, "未找到最早的购买交易日");
            }
            long heldDays = TransactionDayUtil.getHeldDays(firstPurchaseDate, formattedDate);
            sheet.setPurchaseTransactionDate(DateUtil.dateToStr(firstPurchaseDate));
            String totalPrincipalAmount = lastTransaction.getTotalAmount();
            String navStr = fundHistoryNavService.selectLastNotNullFundHistoryNavByConditions(code, formattedDate);
            BigDecimal share = new BigDecimal(lastTransaction.getTotalShare()).setScale(2, RoundingMode.HALF_UP);
            BigDecimal totalAmount = FinancialCalculationUtil.calculateTotalAmount(share, navStr);
            if (lastTransaction.getType().equals(FundTransactionType.REDEMPTION.getDescription())) {
                redemptionDate = transactionDate;
                heldDays = TransactionDayUtil.getHeldDays(firstPurchaseDate, DateUtil.strToDate(transactionDate));
                totalPrincipalAmount = getLastPurchasePrincipalAmount(code, statementSheetList);
                if (totalPrincipalAmount == null) {
                    throw new ExcelException(999, "赎回前没有买入");
                }
                navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, DateUtil.strToDate(redemptionDate));
                totalAmount = FinancialCalculationUtil.calculateRedemptionAmount(share, navStr, new BigDecimal(lastTransaction.getTotalFee()));
            }
            sheet.setRedemptionTransactionDate(redemptionDate);
            sheet.setDividendDate(dividendDate);
            sheet.setHeldDays(String.valueOf(heldDays));
            sheet.setTotalPrincipalAmount(totalPrincipalAmount);
            sheet.setTotalAmount(String.valueOf(totalAmount));
            BigDecimal profit = totalAmount.subtract(new BigDecimal(sheet.getTotalPrincipalAmount()).setScale(2, RoundingMode.HALF_UP));
            sheet.setProfit(String.valueOf(profit));
            BigDecimal dailyNavYield = FinancialCalculationUtil.calculateDailyNavYield(profit, heldDays);
            sheet.setDailyNavYield(String.valueOf(dailyNavYield));
            sheet.setTradingPlatform(lastTransaction.getTradingPlatform());
            sheet.setCompanyName(lastTransaction.getCompanyName());
            list.add(sheet);
        }
        return list;
    }

    private String getLastPurchasePrincipalAmount(String code, List<FundTransactionStatementSheet> statementSheetList) {
        for (int i = 0; i < statementSheetList.size(); i++) {
            FundTransactionStatementSheet statementSheet = statementSheetList.get(i);
            if (statementSheet.getCode().equals(code) && statementSheet.getType().equals(FundTransactionType.REDEMPTION.getDescription())) {
                return statementSheetList.get(i - 1).getTotalAmount();
            }
        }
        return null;
    }

    private Date getFirstPurchaseDate(String code, List<FundTransactionStatementSheet> statementSheetList) throws ParseException {
        for (FundTransactionStatementSheet statementSheet : statementSheetList) {
            if (statementSheet.getCode().equals(code) && statementSheet.getType().equals(FundTransactionType.PURCHASE.getDescription())) {
                return DateUtil.strToDate(statementSheet.getTransactionDate());
            }
        }
        return null;
    }

}
