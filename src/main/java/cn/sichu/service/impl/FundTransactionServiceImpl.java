package cn.sichu.service.impl;

import cn.sichu.entity.*;
import cn.sichu.enums.FundTransactionStatus;
import cn.sichu.enums.FundTransactionType;
import cn.sichu.mapper.FundPositionMapper;
import cn.sichu.mapper.FundPurchaseTransactionMapper;
import cn.sichu.mapper.FundTransactionMapper;
import cn.sichu.service.IFundHistoryNavService;
import cn.sichu.service.IFundTransactionService;
import cn.sichu.utils.DateUtil;
import cn.sichu.utils.FinancialCalculationUtil;
import cn.sichu.utils.TransactionDayUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.text.ParseException;
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
    FundTransactionMapper fundTransactionMapper;
    @Autowired
    FundInformationServiceImpl fundInformationService;
    @Autowired
    IFundPurchaseFeeRateServiceImpl fundPurchaseFeeRateService;
    @Autowired
    IFundHistoryNavService fundHistoryNavService;
    @Autowired
    FundPurchaseTransactionMapper fundPurchaseTransactionMapper;
    @Autowired
    FundPositionMapper fundPositionMapper;

    /**
     * @param fundTransaction fundTransaction
     * @author sichu huang
     * @date 2024/03/09
     **/
    @Override
    public void insertFundTransaction(FundTransaction fundTransaction) {
        fundTransactionMapper.insertFundTransaction(fundTransaction);
    }

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/18
     **/
    @Override
    public void insertFundPurchaseTransaction(FundPurchaseTransaction purchaseTransaction) throws ParseException {
        /* 插入交易表后, 插入总表 */
        FundTransaction fundTransaction = new FundTransaction();
        fundTransaction.setCode(purchaseTransaction.getCode());
        fundTransaction.setApplicationDate(purchaseTransaction.getApplicationDate());
        fundTransaction.setTransactionDate(purchaseTransaction.getTransactionDate());
        fundTransaction.setConfirmationDate(purchaseTransaction.getConfirmationDate());
        fundTransaction.setSettlementDate(purchaseTransaction.getSettlementDate());
        fundTransaction.setAmount(purchaseTransaction.getAmount());
        fundTransaction.setFee(purchaseTransaction.getFee());
        fundTransaction.setNav(purchaseTransaction.getNav());
        fundTransaction.setShare(purchaseTransaction.getShare());
        fundTransaction.setTradingPlatform(purchaseTransaction.getTradingPlatform());
        fundTransaction.setStatus(purchaseTransaction.getStatus());
        fundTransaction.setType(FundTransactionType.PURCHASE.getCode());
        insertFundTransaction(fundTransaction);
        /* 更新持仓表 */
        if (Objects.equals(purchaseTransaction.getStatus(), FundTransactionStatus.HELD.getCode())) {
            insertFundPositionByFundPurchaseTransaction(purchaseTransaction);
        }
        updateHeldDaysAndUpdateDateForFundPosition(purchaseTransaction);
    }

    /**
     * TODO: 对每一步set操作进行判空, 直接抛出自定义异常
     *
     * @param code            code
     * @param applicationDate applicationDate
     * @param amount          amount
     * @param tradingPlatform tradingPlatform
     * @author sichu huang
     * @date 2024/03/10
     **/
    @Override
    public void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, BigDecimal amount,
        String tradingPlatform) throws IOException, ParseException {
        Date currentDate = new Date();
        FundPurchaseTransaction transaction = new FundPurchaseTransaction();
        /* set code, applicationDate, amount, type, tradingPlatform */
        transaction.setCode(code);
        transaction.setApplicationDate(applicationDate);
        transaction.setAmount(amount);
        transaction.setTradingPlatform(tradingPlatform);
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
            Date settlementDate = TransactionDayUtil.getNextNTransactionDate(transactionDate, n);
            transaction.setSettlementDate(settlementDate);
            /* set status */
            if (currentDate.getTime() < settlementDate.getTime()) {
                transaction.setStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
            } else {
                transaction.setStatus(FundTransactionStatus.HELD.getCode());
            }
        }
        /* set fee */
        List<FundPurchaseFeeRate> fundPurchaseFeeRates =
            fundPurchaseFeeRateService.selectFundPurchaseFeeRateByConditions(code, tradingPlatform);
        if (!fundPurchaseFeeRates.isEmpty()) {
            for (int i = 0; i < fundPurchaseFeeRates.size(); i++) {
                FundPurchaseFeeRate fundPurchaseFeeRate = fundPurchaseFeeRates.get(i);
                String feeRate = fundPurchaseFeeRate.getFeeRate();
                if (!feeRate.endsWith("%")) {
                    transaction.setFee(new BigDecimal(feeRate));
                    break;
                }
                if (amount.compareTo(new BigDecimal(fundPurchaseFeeRate.getFeeRateChangeAmount())) < 0) {
                    transaction.setFee(FinancialCalculationUtil.calculatePurchaseFee(amount, feeRate));
                    break;
                }
                if (i > 0
                    && amount.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i - 1).getFeeRateChangeAmount())) >= 0
                    && amount.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i).getFeeRateChangeAmount())) < 0) {
                    transaction.setFee(FinancialCalculationUtil.calculatePurchaseFee(amount, feeRate));
                    break;
                }
            }
        }
        /* set nav, share */
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
        while (navStr == null || navStr.equals("")) {
            List<FundHistoryNav> fundHistoryNavs = fundHistoryNavService.selectLastFundHistoryNavDateByConditions(code);
            Date lastNavDate = fundHistoryNavs.get(0).getNavDate();
            String callback = fundHistoryNavService.selectCallbackByCode(code);
            /* 更新净值表后再查表 */
            if (transaction.getTransactionDate().getTime() >= lastNavDate.getTime()) {
                fundHistoryNavService.insertFundHistoryNavInformation(code, DateUtil.dateToStr(lastNavDate),
                    DateUtil.dateToStr(transactionDate), callback);
                navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
                break;
            } else {
                int tryCount = 4;
                for (int i = 0; i < tryCount; i++) {
                    if (navStr != null && !navStr.equals("")) {
                        break;
                    }
                    Date date;
                    switch (i) {
                        case 0 -> date = TransactionDayUtil.getLastNTransactionDate(lastNavDate, 3);
                        case 1 -> date = TransactionDayUtil.getLastNTransactionDate(lastNavDate, 7);
                        case 2 -> date = TransactionDayUtil.getLastNTransactionDate(lastNavDate, 30);
                        default -> {
                            Logger logger = LoggerFactory.getLogger(FundTransactionServiceImpl.class);
                            logger.info("==========需要手动初始化: insertFundHistoryNavInformation==========");
                            continue; // Skip the rest of the loop body and continue with the next iteration
                        }
                    }
                    fundHistoryNavService.insertFundHistoryNavInformation(code, DateUtil.dateToStr(date),
                        DateUtil.dateToStr(transactionDate), callback);
                    navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
                }
            }
        }
        if (navStr != null && !navStr.equals("")) {
            transaction.setNav(new BigDecimal(navStr));
            transaction.setShare(FinancialCalculationUtil.calculateShare(amount, transaction.getFee(), navStr));
        }

        fundPurchaseTransactionMapper.insertFundPurchaseTransaction(transaction);
        insertFundPurchaseTransaction(transaction);
    }

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/20
     **/
    @Override
    public void insertFundPositionByFundPurchaseTransaction(FundPurchaseTransaction purchaseTransaction)
        throws ParseException {
        String code = purchaseTransaction.getCode();
        FundPosition fundPosition = new FundPosition();
        fundPosition.setCode(code);
        fundPosition.setTransactionDate(purchaseTransaction.getTransactionDate());
        fundPosition.setInitiationDate(purchaseTransaction.getSettlementDate());
        List<FundPosition> prevPosition = fundPositionMapper.selectLastFunPositionByCode(code);
        if (prevPosition.isEmpty()) {
            fundPosition.setTotalAmount(purchaseTransaction.getAmount());
            fundPosition.setTotalPurchaseFee(purchaseTransaction.getFee());
            fundPosition.setHeldShare(purchaseTransaction.getShare());
        } else {
            fundPosition.setTotalAmount(prevPosition.get(0).getTotalAmount().add(purchaseTransaction.getAmount()));
            fundPosition.setTotalPurchaseFee(
                prevPosition.get(0).getTotalPurchaseFee().add(purchaseTransaction.getFee()));
            fundPosition.setHeldShare(prevPosition.get(0).getHeldShare().add(purchaseTransaction.getShare()));
        }
        Date currentDate = new Date();
        long heldDays = TransactionDayUtil.getHeldDays(currentDate, purchaseTransaction.getTransactionDate());
        fundPosition.setHeldDays((int)heldDays);
        fundPosition.setUpdateDate(DateUtil.formatDate(currentDate));
        fundPositionMapper.insertFundPosition(fundPosition);
    }

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
     * @return java.util.List<cn.sichu.entity.FundPurchaseTransaction>
     * @author sichu huang
     * @date 2024/03/17
     **/
    @Override
    public List<FundPurchaseTransaction> selectAllFundPurchaseTransactions() {
        return fundPurchaseTransactionMapper.selectAllFundPurchaseTransactions();
    }

    /**
     * @param code   code
     * @param status status
     * @return java.util.List<cn.sichu.entity.FundPurchaseTransaction>
     * @author sichu huang
     * @date 2024/03/19
     **/
    @Override
    public List<FundPurchaseTransaction> selectAllFundPurchaseTransactionsByConditions(String code, Integer status) {
        return fundPurchaseTransactionMapper.selectAllFundPurchaseTransactionsByConditions(code, status);
    }

    @Override
    public List<FundPurchaseTransaction> selectAllFundPurchaseTransactionsByStatus(Integer status) {
        return fundPurchaseTransactionMapper.selectAllFundPurchaseTransactionsByStatus(status);
    }

    /**
     * TODO: 完善逻辑
     *
     * @param date date
     * @author sichu huang
     * @date 2024/03/16
     **/
    @Override
    public void updateNavAndShareForFundPurchaseTransaction(Date date) {
        List<FundPurchaseTransaction> transactions = fundPurchaseTransactionMapper.selectAllFundPurchaseTransactions();
        for (FundPurchaseTransaction transaction : transactions) {
            if (date.getTime() < transaction.getSettlementDate().getTime()) {
                continue;
            }
            if (transaction.getNav() == null || transaction.getShare() == null) {
                String code = transaction.getCode();
                String navStr =
                    fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
                if (navStr != null && !navStr.equals("")) {
                    BigDecimal amount = transaction.getAmount();
                    BigDecimal fee = transaction.getFee();
                    BigDecimal share = FinancialCalculationUtil.calculateShare(amount, fee, navStr);
                    transaction.setNav(new BigDecimal(navStr));
                    transaction.setShare(share);
                    fundPurchaseTransactionMapper.updateNavAndShareForFundPurchaseTransaction(transaction);
                    updateNavAndShareForFundTransaction(date);
                }
            }
        }
    }

    /**
     * TODO: 完善逻辑
     *
     * @param date date
     * @author sichu huang
     * @date 2024/03/18
     **/
    @Override
    public void updateNavAndShareForFundTransaction(Date date) {
        List<FundTransaction> transactions = fundTransactionMapper.selectPurchaseTransactionsFromFundTransactions();
        for (FundTransaction transaction : transactions) {
            if (date.getTime() < transaction.getSettlementDate().getTime()) {
                continue;
            }
            if (transaction.getNav() == null || transaction.getShare() == null) {
                String code = transaction.getCode();
                String navStr =
                    fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
                if (navStr != null && !navStr.equals("")) {
                    BigDecimal amount = transaction.getAmount();
                    BigDecimal fee = transaction.getFee();
                    BigDecimal share = FinancialCalculationUtil.calculateShare(amount, fee, navStr);
                    transaction.setNav(new BigDecimal(navStr));
                    transaction.setShare(share);
                    fundTransactionMapper.updateNavAndShareForFundTransaction(transaction);
                }
            }
        }
    }

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/16
     **/
    @Override
    public void updateStatusForFundTransaction(Date date) {
        List<FundTransaction> transactions = fundTransactionMapper.selectAllFundTransactions();
        for (FundTransaction transaction : transactions) {
            if (!Objects.equals(transaction.getType(), FundTransactionType.PURCHASE.getCode())) {
                return;
            }
            Date settlementDate = transaction.getSettlementDate();
            if (transaction.getStatus() == null) {
                if (date.getTime() < settlementDate.getTime()) {
                    transaction.setStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
                } else {
                    transaction.setStatus(FundTransactionStatus.HELD.getCode());
                }
                fundTransactionMapper.updateStatusForFundTransaction(transaction);
            }
        }
    }

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/18
     **/
    @Override
    public void updateStatusForFundPurchaseTransaction(Date date) {
        List<FundPurchaseTransaction> transactions = fundPurchaseTransactionMapper.selectAllFundPurchaseTransactions();
        for (FundPurchaseTransaction transaction : transactions) {
            Date settlementDate = transaction.getSettlementDate();
            if (transaction.getStatus() == null) {
                if (date.getTime() < settlementDate.getTime()) {
                    transaction.setStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
                } else {
                    transaction.setStatus(FundTransactionStatus.HELD.getCode());
                }
                fundPurchaseTransactionMapper.updateStatusForFundPurchaseTransaction(transaction);
            }
        }
    }

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/19
     **/
    @Override
    public void updateHeldDaysAndUpdateDateForFundPosition(FundPurchaseTransaction purchaseTransaction)
        throws ParseException {
        String code = purchaseTransaction.getCode();
        List<FundPosition> fundPositions = fundPositionMapper.selectAllFundPositionByCode(code);
        if (fundPositions.isEmpty()) {
            return;
        }
        Date currentDate = new Date();
        for (FundPosition fundPosition : fundPositions) {
            long heldDays = TransactionDayUtil.getHeldDays(currentDate, fundPosition.getTransactionDate());
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(DateUtil.formatDate(currentDate));
            fundPositionMapper.updateHeldDaysAndUpdateDateForFundPosition(fundPosition);
        }
    }

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    @Override
    public void updateHeldDaysAndUpdateDateForFundPosition(Date date) throws ParseException {
        List<FundPosition> fundPositions = fundPositionMapper.selectallFundPosition();
        for (FundPosition fundPosition : fundPositions) {
            long heldDays = TransactionDayUtil.getHeldDays(date, fundPosition.getTransactionDate());
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(DateUtil.formatDate(date));
            fundPositionMapper.updateHeldDaysAndUpdateDateForFundPosition(fundPosition);
        }
    }

    /**
     * @param date date
     * @author sichu huang
     * @date 2024/03/20
     **/
    @Override
    public void updateStatusForTransactionInTransit(Date date) throws ParseException {
        /* update table fund_purchase_transaction */
        List<FundPurchaseTransaction> fundPurchaseTransactions =
            fundPurchaseTransactionMapper.selectAllFundPurchaseTransactionsByStatus(
                FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
        for (FundPurchaseTransaction transaction : fundPurchaseTransactions) {
            if (date.getTime() >= transaction.getSettlementDate().getTime()) {
                transaction.setStatus(FundTransactionStatus.HELD.getCode());
                insertFundPositionByFundPurchaseTransaction(transaction);
            }
            fundPurchaseTransactionMapper.updateStatusForFundPurchaseTransaction(transaction);
        }
        // TODO: update table fund_redemption_transaction
        /* update table fund_transaction */
        List<FundTransaction> fundTransactions = fundTransactionMapper.selectAllFundTransactionsInTransit();
        for (FundTransaction transaction : fundTransactions) {
            if (date.getTime() >= transaction.getSettlementDate().getTime()) {
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.HELD.getCode());
                }
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
                }
            }
            fundTransactionMapper.updateStatusForFundTransaction(transaction);
        }
    }
}
