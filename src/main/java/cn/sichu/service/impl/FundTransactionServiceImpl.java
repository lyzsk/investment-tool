package cn.sichu.service.impl;

import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundPurchaseFeeRate;
import cn.sichu.entity.FundTransaction;
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
    public List<FundTransaction> selectAllFundTransaction() {
        return fundTransactionMapper.selectAllFundTransaction();
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
        if (type != 0) {
            return;
        }
        FundTransaction transaction = new FundTransaction();
        transaction.setCode(code);
        transaction.setAmount(amount);
        transaction.setType(type);
        transaction.setTradingPlatform(tradingPlatform);
        /* set shortName */
        List<FundInformation> fundInformations = fundInformationService.selectFundShortNameByCode(code);
        if (!fundInformations.isEmpty()) {
            String shortName = fundInformations.get(0).getShortName();
            transaction.setShortName(shortName);
        }
        /* set applicationDate*/
        transaction.setApplicationDate(applicationDate);
        /* set transactionDate */
        Date transactionDate = TransactionDayUtil.isTransactionDate(applicationDate) ? applicationDate :
            TransactionDayUtil.getNextTransactionDate(applicationDate);
        transaction.setTransactionDate(transactionDate);
        /* set confirmationDate  */
        Date confirmationDate = transactionDate;
        transaction.setConfirmationDate(confirmationDate);
        /* set settlementDate */
        List<FundInformation> purchaseInformations = fundInformationService.selectFundTransactionProcessByCode(code);
        if (!purchaseInformations.isEmpty()) {
            FundInformation information = purchaseInformations.get(0);
            Integer n = information.getPurchaseConfirmationProcess();
            Date settlementDate = new Date(confirmationDate.getTime());
            transaction.setSettlementDate(TransactionDayUtil.getNextNTransactionDate(settlementDate, n));
        }

        /* set nav, fee, share */
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd");
        String nav = fundHistoryNavService.selectFundHistoryNavByConditions(code, sdf.format(transactionDate));
        if (nav != null && !nav.equals("")) {
            transaction.setNav(nav);
            List<FundPurchaseFeeRate> fundPurchaseFeeRates =
                fundPurchaseFeeRateService.selectFundPurchaseFeeRateByConditions(code, tradingPlatform);
            BigDecimal amountDecimal = new BigDecimal(amount);
            for (int i = 0; i < fundPurchaseFeeRates.size(); i++) {
                FundPurchaseFeeRate fundPurchaseFeeRate = fundPurchaseFeeRates.get(i);
                if (i == 0
                    && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i).getFeeRateChangeAmount()))
                    < 0) {
                    processTransaction(transaction, fundPurchaseFeeRate);
                    break;
                }
                if (i > 0 && i == fundPurchaseFeeRates.size() - 1) {
                    String fee = fundPurchaseFeeRates.get(fundPurchaseFeeRates.size() - 1).getFeeRate();
                    transaction.setFee(fee);
                    transaction.setShare(FinancialCalculationUtil.calculateShare(amount, fee, nav));
                    break;
                }
                if (i > 0
                    && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i - 1).getFeeRateChangeAmount()))
                    >= 0
                    && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i).getFeeRateChangeAmount()))
                    < 0) {
                    processTransaction(transaction, fundPurchaseFeeRate);
                    break;
                }
            }
        }

        insertFundTransaction(transaction);
    }

    private void processTransaction(FundTransaction transaction, FundPurchaseFeeRate fundPurchaseFeeRate) {
        String amount = transaction.getAmount();
        String rate = fundPurchaseFeeRate.getFeeRate();
        String fee = FinancialCalculationUtil.calculatePurchaseFee(amount, rate);
        transaction.setFee(fee);
        String share = FinancialCalculationUtil.calculateShare(amount, fee, transaction.getNav());
        transaction.setShare(share);
    }

    private boolean shouldProcessTransaction(int i, String amount, List<FundPurchaseFeeRate> fundPurchaseFeeRates) {
        BigDecimal amountDecimal = new BigDecimal(amount);
        if (i == 0
            && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i).getFeeRateChangeAmount())) < 0) {
            return true;
        }
        return i > 0
            && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i - 1).getFeeRateChangeAmount())) >= 0
            && amountDecimal.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i).getFeeRateChangeAmount())) < 0;
    }

}
