package cn.sichu.service.impl;

import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundTransaction;
import cn.sichu.mapper.FundTransactionMapper;
import cn.sichu.service.IFundTransactionService;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.RoundingMode;
import java.text.DecimalFormat;
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
    public void insertFundTransactionByConditions(String code, String applicationDate, String amount, Integer type,
        String tradingPlatform) throws ParseException, IOException {
        FundTransaction transaction = new FundTransaction();
        transaction.setCode(code);
        String shortName = "";
        List<FundInformation> fundInformations = fundInformationService.selectFundShortNameByCode(code);
        for (FundInformation fundInformation : fundInformations) {
            shortName = fundInformation.getShortName();
        }
        transaction.setShortName(shortName);

        Date parsedApplicationDate = new SimpleDateFormat("yyyy-MM-dd").parse(applicationDate);
        if (TransactionDayUtil.isTransactionDate(parsedApplicationDate)) {
            transaction.setApplicationDate(parsedApplicationDate);
        } else {
            parsedApplicationDate = TransactionDayUtil.getNextTransactionDate(parsedApplicationDate);
            transaction.setApplicationDate(parsedApplicationDate);
        }
        /* parsedApplicationDate = T日 */
        if (type == 0 && TransactionDayUtil.isTransactionDate(parsedApplicationDate)) {
            transaction.setConfirmationDate(parsedApplicationDate);
            List<FundInformation> purchaseInformations =
                fundInformationService.selectFundTransactionProcessByCode(code);
            for (FundInformation information : purchaseInformations) {
                Integer n = information.getPurchaseConfirmationProcess();
                Date settlementDate = new Date(parsedApplicationDate.getTime());
                transaction.setSettlementDate(TransactionDayUtil.getNextNTransactionDate(settlementDate, n));
            }
        }
        if (type == 1 && TransactionDayUtil.isTransactionDate(parsedApplicationDate)) {
            List<FundInformation> redemptionInformations =
                fundInformationService.selectFundTransactionProcessByCode(code);
            for (FundInformation information : redemptionInformations) {
                Integer confirmationN = information.getRedemptionConfirmationProcess();
                Integer settlementN = information.getRedemptionSettlementProcess();
                Date confirmationDate = new Date(parsedApplicationDate.getTime());
                Date settlementDate = new Date(parsedApplicationDate.getTime());
                transaction.setConfirmationDate(
                    TransactionDayUtil.getNextNTransactionDate(confirmationDate, confirmationN));
                transaction.setSettlementDate(TransactionDayUtil.getNextNTransactionDate(settlementDate, settlementN));
            }

        }
        if (type == 2 && TransactionDayUtil.isTransactionDate(parsedApplicationDate)) {
            transaction.setConfirmationDate(parsedApplicationDate);
            transaction.setSettlementDate(parsedApplicationDate);
        }
        List<FundInformation> purchaseFeeInformations = fundInformationService.selectFundPurchaseFeeRateByCode(code);
        for (FundInformation information : purchaseFeeInformations) {
            String rate = information.getPurchaseFeeRate();
            transaction.setFee(calculateFeeByRate(amount, rate));
        }
        transaction.setAmount(amount);
        transaction.setType(type);
        transaction.setTradingPlatform(tradingPlatform);

        insertFundTransaction(transaction);
    }

    /**
     * @param amount
     * @param rate
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/10
     **/
    private String calculateFeeByRate(String amount, String rate) {
        double v = Double.parseDouble(amount);
        String substring = rate.substring(0, rate.length() - 1);
        double r = Double.parseDouble(substring);
        double fee = v * r * 0.01;
        DecimalFormat df = new DecimalFormat("0.00");
        df.setRoundingMode(RoundingMode.HALF_UP);
        return df.format(fee);
    }
}
