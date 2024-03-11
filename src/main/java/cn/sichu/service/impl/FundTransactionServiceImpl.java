package cn.sichu.service.impl;

import cn.sichu.entity.FundInformation;
import cn.sichu.entity.FundTransaction;
import cn.sichu.mapper.FundTransactionMapper;
import cn.sichu.service.IFundTransactionService;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.text.DecimalFormat;
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
    public void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, String amount,
        Integer type, String tradingPlatform) throws IOException {
        if (type != 0) {
            return;
        }
        FundTransaction transaction = new FundTransaction();
        transaction.setCode(code);
        String shortName = "";
        List<FundInformation> fundInformations = fundInformationService.selectFundShortNameByCode(code);
        for (FundInformation fundInformation : fundInformations) {
            shortName = fundInformation.getShortName();
        }
        transaction.setShortName(shortName);
        // TODO: applicationDate 和 transactionDate 区分, 而不是强转, 需要加入 transactionDate 字段
        if (TransactionDayUtil.isTransactionDate(applicationDate)) {
            transaction.setApplicationDate(applicationDate);
        } else {
            applicationDate = TransactionDayUtil.getNextTransactionDate(applicationDate);
            transaction.setApplicationDate(applicationDate);
        }
        transaction.setConfirmationDate(applicationDate);
        List<FundInformation> purchaseInformations = fundInformationService.selectFundTransactionProcessByCode(code);
        for (FundInformation information : purchaseInformations) {
            Integer n = information.getPurchaseConfirmationProcess();
            Date settlementDate = new Date(applicationDate.getTime());
            transaction.setSettlementDate(TransactionDayUtil.getNextNTransactionDate(settlementDate, n));
        }

        // if (type == 1 && TransactionDayUtil.isTransactionDate(applicationDate)) {
        //     List<FundInformation> redemptionInformations =
        //         fundInformationService.selectFundTransactionProcessByCode(code);
        //     for (FundInformation information : redemptionInformations) {
        //         Integer confirmationN = information.getRedemptionConfirmationProcess();
        //         Integer settlementN = information.getRedemptionSettlementProcess();
        //         Date confirmationDate = new Date(applicationDate.getTime());
        //         Date settlementDate = new Date(applicationDate.getTime());
        //         transaction.setConfirmationDate(
        //             TransactionDayUtil.getNextNTransactionDate(confirmationDate, confirmationN));
        //         transaction.setSettlementDate(TransactionDayUtil.getNextNTransactionDate(settlementDate, settlementN));
        //     }
        //
        // }
        // if (type == 2 && TransactionDayUtil.isTransactionDate(applicationDate)) {
        //     transaction.setConfirmationDate(applicationDate);
        //     transaction.setSettlementDate(applicationDate);
        // }

        String fee = "";
        List<FundInformation> purchaseFeeInformations = fundInformationService.selectFundPurchaseFeeRateByCode(code);
        for (FundInformation information : purchaseFeeInformations) {
            String rate = information.getPurchaseFeeRate();
            fee = calculateFeeByRate(amount, rate);
            transaction.setFee(fee);
        }
        // Map<String, String> transactionDateNavMap = JsoupUtil.getTransactionDateNavMap(code);
        // String formatedParsedApplicationDate = sdf.format(applicationDate);
        // TODO: nav, share 应该在update时by code, by date更新
        // String nav = transactionDateNavMap.get(formatedParsedApplicationDate);
        // String share = "";
        // if (nav != null && !nav.equals("")) {
        //     transaction.setNav(nav);
        //     share = calculateShare(amount, fee, nav);
        //     transaction.setShare(share);
        // }
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

    /**
     * @param amount
     * @param fee
     * @param nav
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/10
     **/
    private String calculateShare(String amount, String fee, String nav) {
        BigDecimal amountDecimal = new BigDecimal(amount);
        BigDecimal feeDecimal = new BigDecimal(fee);
        BigDecimal navDecimal = new BigDecimal(nav);
        BigDecimal shareDecimal = amountDecimal.subtract(feeDecimal).divide(navDecimal, 4, BigDecimal.ROUND_HALF_UP);
        shareDecimal = shareDecimal.setScale(2, BigDecimal.ROUND_HALF_UP);
        return shareDecimal.toString();
    }
}
