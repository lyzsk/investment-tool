package cn.sichu.service.impl;

import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundPurchaseFeeRate;
import cn.sichu.entity.FundTransaction;
import cn.sichu.enums.FundTransactionStatus;
import cn.sichu.enums.FundTransactionType;
import cn.sichu.mapper.FundTransactionMapper;
import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.service.IFundTransactionService;
import cn.sichu.utils.FinancialCalculationUtil;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Objects;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Service
public class FundTransactionServiceImpl implements IFundTransactionService {
    @Autowired
    private FundTransactionMapper fundTransactionMapper;
    @Autowired
    private FundInformationServiceImpl fundInformationService;
    @Autowired
    private IFundPurchaseFeeRateServiceImpl fundPurchaseFeeRateService;
    @Autowired
    private IFundHistoryNavService fundHistoryNavService;

    /**
     * @param code
     * @param applicationDate
     * @param share
     * @param type
     * @author sichu huang
     * @date 2024/03/11
     **/
    // @Override
    // public void insertFundRedemptionTransactionByConditions(String code, Date applicationDate, String share,
    //     Integer type) throws IOException {
    //     if (type != 1) {
    //         return;
    //     }
    //     FundTransaction transaction = new FundTransaction();
    //     transaction.setCode(code);
    //     String shortName = "";
    //     List<FundInformation> fundInformations = fundInformationService.selectFundShortNameByCode(code);
    //     for (FundInformation fundInformation : fundInformations) {
    //         shortName = fundInformation.getShortName();
    //     }
    //     transaction.setShortName(shortName);
    //     // TODO: applicationDate 和 transactionDate 区分, 而不是强转, 需要加入 transactionDate 字段
    //     if (TransactionDayUtil.isTransactionDate(applicationDate)) {
    //         transaction.setApplicationDate(applicationDate);
    //     } else {
    //         applicationDate = TransactionDayUtil.getNextTransactionDate(applicationDate);
    //         transaction.setApplicationDate(applicationDate);
    //     }
    //     List<FundInformation> redemptionInformations = fundInformationService.selectFundTransactionProcessByCode(code);
    //     for (FundInformation information : redemptionInformations) {
    //         Integer confirmationN = information.getRedemptionConfirmationProcess();
    //         Integer settlementN = information.getRedemptionSettlementProcess();
    //         Date confirmationDate = new Date(applicationDate.getTime());
    //         Date settlementDate = new Date(applicationDate.getTime());
    //         transaction.setConfirmationDate(
    //             TransactionDayUtil.getNextNTransactionDate(confirmationDate, confirmationN));
    //         transaction.setSettlementDate(TransactionDayUtil.getNextNTransactionDate(settlementDate, settlementN));
    //     }
    //     // TODO: 先select到nav, 再计算fee
    //     String fee = "";
    //     List<FundInformation> redemptionFeeInformations =
    //         fundInformationService.selectFundRedemptionFeeRateByCode(code);
    //     for (FundInformation information : redemptionFeeInformations) {
    //         String rate = information.getRedemptionFeeRate();
    //         fee = calculateRedemptionFeeByRate(share, nav, rate);
    //         transaction.setFee(fee);
    //     }
    //     insertFundTransaction(transaction);
    // }

    /**
     * @return java.util.List<cn.sichu.entity.FundTransaction>
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public List<FundTransaction> selectAllFundTransactions() {
        return fundTransactionMapper.selectAllFundTransactions();
    }

    /**
     * @param fundTransaction
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public void insertFundTransaction(FundTransaction fundTransaction) {
        fundTransactionMapper.insertFundTransaction(fundTransaction);
    }

    /**
     * TODO: 对每一步set操作进行判空, 直接抛出自定义异常
     *
     * @param code
     * @param applicationDate
     * @param amount
     * @param type
     * @param tradingPlatform
     * @author sichu huang
     * @date 2024/03/10
     **/
    @Override
    public void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, String amount,
        Integer type, String tradingPlatform) throws IOException, ParseException {
        if (!Objects.equals(type, FundTransactionType.PURCHASE.getCode())) {
            return;
        }
        FundTransaction transaction = new FundTransaction();
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd");
        /* set code, applicationDate, amount, type, tradingPlatform */
        transaction.setCode(code);
        transaction.setApplicationDate(applicationDate);
        transaction.setAmount(amount);
        transaction.setType(type);
        transaction.setTradingPlatform(tradingPlatform);
        /* set shortName */
        List<FundInformation> fundInformations = fundInformationService.selectFundShortNameByCode(code);
        if (!fundInformations.isEmpty()) {
            String shortName = fundInformations.get(0).getShortName();
            transaction.setShortName(shortName);
        }
        /* set transactionDate */
        Date transactionDate = TransactionDayUtil.isTransactionDate(applicationDate) ? applicationDate :
            TransactionDayUtil.getNextTransactionDate(applicationDate);
        transaction.setTransactionDate(transactionDate);
        /* set confirmationDate  */
        transaction.setConfirmationDate(transactionDate);
        /* set settlementDate */
        List<FundInformation> purchaseProcess = fundInformationService.selectFundTransactionProcessByCode(code);
        if (!purchaseProcess.isEmpty()) {
            FundInformation information = purchaseProcess.get(0);
            Integer n = information.getPurchaseConfirmationProcess();
            Date settlementDate = TransactionDayUtil.getNextNTransactionDate(new Date(transactionDate.getTime()), n);
            transaction.setSettlementDate(settlementDate);
            /* set status */
            if (new Date().getTime() < settlementDate.getTime()) {
                transaction.setStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
            } else {
                transaction.setStatus(FundTransactionStatus.HELD.getCode());
            }
        }
        /* set fee */
        String fee;
        List<FundPurchaseFeeRate> fundPurchaseFeeRates =
            fundPurchaseFeeRateService.selectFundPurchaseFeeRateByConditions(code, tradingPlatform);
        if (!fundPurchaseFeeRates.isEmpty()) {
            BigDecimal amountDecimal = new BigDecimal(amount);
            for (int i = 0; i < fundPurchaseFeeRates.size(); i++) {
                FundPurchaseFeeRate fundPurchaseFeeRate = fundPurchaseFeeRates.get(i);
                String feeRate = fundPurchaseFeeRate.getFeeRate();
                if (!feeRate.endsWith("%")) {
                    transaction.setFee(feeRate);
                    break;
                }
                if (amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRate.getFeeRateChangeAmount())) < 0) {
                    fee = FinancialCalculationUtil.calculatePurchaseFee(amount, feeRate);
                    transaction.setFee(fee);
                    break;
                }
                if (i > 0
                    && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i - 1).getFeeRateChangeAmount()))
                    >= 0
                    && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i).getFeeRateChangeAmount()))
                    < 0) {
                    fee = FinancialCalculationUtil.calculatePurchaseFee(amount, feeRate);
                    transaction.setFee(fee);
                    break;
                }
            }
        }
        /* set nav, share */
        String nav = fundHistoryNavService.selectFundHistoryNavByConditions(code, sdf.format(transactionDate));
        if (nav != null && !nav.equals("")) {
            transaction.setNav(nav);
            String share = FinancialCalculationUtil.calculateShare(amount, transaction.getFee(), nav);
            transaction.setShare(share);
        }

        insertFundTransaction(transaction);
    }

    /**
     * @param date
     * @author sichu huang
     * @date 2024/03/16
     **/
    @Override
    public void updateNavAndShareForFundPurchaseTransaction(Date date) throws ParseException {
        // TODO: 改成 selectAllFundPurchaseTransactions, 然后 getType != 0 break
        List<FundTransaction> fundTransactions = fundTransactionMapper.selectAllFundTransactions();
        for (FundTransaction transaction : fundTransactions) {
            if (!Objects.equals(transaction.getType(), FundTransactionType.PURCHASE.getCode())) {
                continue;
            }
            if (date.getTime() < transaction.getSettlementDate().getTime()) {
                continue;
            }
            if (transaction.getNav() == null || transaction.getNav().equals("") || transaction.getShare() == null
                || transaction.getShare().equals("")) {
                String code = transaction.getCode();
                String nav =
                    fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
                if (nav != null && !nav.equals("")) {
                    String amount = transaction.getAmount();
                    String fee = transaction.getFee();
                    String share = FinancialCalculationUtil.calculateShare(amount, fee, nav);
                    transaction.setNav(nav);
                    transaction.setShare(share);
                    fundTransactionMapper.updateNavAndShareForFundPurchaseTransaction(transaction);
                }
            }
        }
    }

    /**
     * @param date
     * @author sichu huang
     * @date 2024/03/16
     **/
    @Override
    public void updateStatusForFundPurchaseTransactions(Date date) {
        List<FundTransaction> fundTransactions = fundTransactionMapper.selectAllFundTransactions();
        for (FundTransaction transaction : fundTransactions) {
            Integer type = transaction.getType();
            if (!Objects.equals(type, FundTransactionType.PURCHASE.getCode())) {
                return;
            }
            Date settlementDate = transaction.getSettlementDate();
            if (transaction.getStatus() == null) {
                if (date.getTime() < settlementDate.getTime()) {
                    transaction.setStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
                } else {
                    transaction.setStatus(FundTransactionStatus.HELD.getCode());
                }
                fundTransactionMapper.updateStatusForFundPurchaseTransactions(transaction);
            }
        }
    }
}
