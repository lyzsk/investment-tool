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
     * @param fundPurchaseTransaction fundPurchaseTransaction
     * @author sichu huang
     * @date 2024/03/21
     **/
    @Override
    public void insertFundTransactionByFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction) {
        FundTransaction fundTransaction = new FundTransaction();
        fundTransaction.setCode(fundPurchaseTransaction.getCode());
        fundTransaction.setApplicationDate(fundPurchaseTransaction.getApplicationDate());
        fundTransaction.setTransactionDate(fundPurchaseTransaction.getTransactionDate());
        fundTransaction.setConfirmationDate(fundPurchaseTransaction.getConfirmationDate());
        fundTransaction.setSettlementDate(fundPurchaseTransaction.getSettlementDate());
        fundTransaction.setAmount(fundPurchaseTransaction.getAmount());
        fundTransaction.setFee(fundPurchaseTransaction.getFee());
        fundTransaction.setNav(fundPurchaseTransaction.getNav());
        fundTransaction.setShare(fundPurchaseTransaction.getShare());
        fundTransaction.setTradingPlatform(fundPurchaseTransaction.getTradingPlatform());
        fundTransaction.setStatus(fundPurchaseTransaction.getStatus());
        fundTransaction.setType(FundTransactionType.PURCHASE.getCode());
        fundTransactionMapper.insertFundTransaction(fundTransaction);
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
    public void insertFundPurchaseTransactionByConditions(String code, Date applicationDate, BigDecimal amount, String tradingPlatform)
        throws IOException, ParseException {
        Date currentDate = new Date();
        FundPurchaseTransaction transaction = new FundPurchaseTransaction();
        /* set code, applicationDate, amount, type, tradingPlatform */
        transaction.setCode(code);
        transaction.setApplicationDate(applicationDate);
        transaction.setAmount(amount);
        transaction.setTradingPlatform(tradingPlatform);
        /* set transactionDate */
        Date transactionDate =
            TransactionDayUtil.isTransactionDate(applicationDate) ? applicationDate : TransactionDayUtil.getNextTransactionDate(applicationDate);
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
        List<FundPurchaseFeeRate> fundPurchaseFeeRates = fundPurchaseFeeRateService.selectFundPurchaseFeeRateByConditions(code, tradingPlatform);
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
                if (i > 0 && amount.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i - 1).getFeeRateChangeAmount())) >= 0
                    && amount.compareTo(new BigDecimal(fundPurchaseFeeRates.get(i).getFeeRateChangeAmount())) < 0) {
                    transaction.setFee(FinancialCalculationUtil.calculatePurchaseFee(amount, feeRate));
                    break;
                }
            }
        }
        /* set nav, share */
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
        if (navStr == null || navStr.equals("")) {
            List<FundHistoryNav> fundHistoryNavs = fundHistoryNavService.selectLastFundHistoryNavDateByConditions(code);
            Date lastNavDate = fundHistoryNavs.get(0).getNavDate();
            String callback = fundHistoryNavService.selectCallbackByCode(code);
            /* 更新净值表后再查表 */
            if (transaction.getTransactionDate().getTime() >= lastNavDate.getTime()) {
                fundHistoryNavService.insertFundHistoryNav(code, DateUtil.dateToStr(lastNavDate), DateUtil.dateToStr(transactionDate), callback);
                navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
            } else {
                int tryCount = 3;
                for (int i = 0; i <= tryCount; i++) {
                    if (navStr != null && !navStr.equals("")) {
                        break;
                    }
                    Date date;
                    switch (i) {
                        case 0 -> date = TransactionDayUtil.getLastNTransactionDate(lastNavDate, 7);
                        case 1 -> date = TransactionDayUtil.getLastNTransactionDate(lastNavDate, 30);
                        case 2 -> date = TransactionDayUtil.getLastNTransactionDate(lastNavDate, 90);
                        default -> date = DateUtil.strToDate("2023-08-01");
                    }
                    fundHistoryNavService.insertFundHistoryNav(code, DateUtil.dateToStr(date), DateUtil.dateToStr(transactionDate), callback);
                    navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
                }
            }
        }
        if (navStr != null && !navStr.equals("")) {
            transaction.setNav(new BigDecimal(navStr));
            transaction.setShare(FinancialCalculationUtil.calculateShare(amount, transaction.getFee(), navStr));
            /* insert fund_position table */
            if (Objects.equals(transaction.getStatus(), FundTransactionStatus.HELD.getCode())) {
                insertFundPositionByFundPurchaseTransaction(transaction);
            }
        }
        /* insert fund_purchase_transaction table */
        fundPurchaseTransactionMapper.insertFundPurchaseTransaction(transaction);
        /* insert fund_transaction table */
        insertFundTransactionByFundPurchaseTransaction(transaction);
    }

    /**
     * @param purchaseTransaction purchaseTransaction
     * @author sichu huang
     * @date 2024/03/20
     **/
    @Override
    public void insertFundPositionByFundPurchaseTransaction(FundPurchaseTransaction purchaseTransaction) throws IOException {
        String code = purchaseTransaction.getCode();
        BigDecimal amount = purchaseTransaction.getAmount();
        BigDecimal fee = purchaseTransaction.getFee();
        BigDecimal share = purchaseTransaction.getShare();
        FundPosition fundPosition = initFundPositionFromPurchaseTransaction(purchaseTransaction);
        List<FundPosition> fundPositions = fundPositionMapper.selectAllFundPositionByCodeOrderByTransactionDate(code);
        if (fundPositions.isEmpty()) {
            /* 若无对应code的持仓数据: 直接插入数据 */
            setFundPositionDataAndInsert(fundPosition, amount, fee, share);
        } else {
            /* 若有对应code的持仓数据: 日期最小的 fundPosition 为参照开始判断 */
            FundPosition position = fundPositions.get(0);
            if (purchaseTransaction.getTransactionDate().before(position.getTransactionDate())) {
                handleFundPositionBeforeTransactionDate(fundPosition, amount, fee, share);
            } else if (purchaseTransaction.getTransactionDate().after(position.getTransactionDate())) {
                handleFundPositionAfterTransactionDate(fundPosition, amount, fee, share);
            } else {
                handleFundPositionEqualsTransactionDate(fundPosition, amount, fee, share);
            }
        }
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
     * @author sichu huang
     * @date 2024/03/16
     **/
    @Override
    public void updateNavAndShareForFundPurchaseTransaction() {
        List<FundPurchaseTransaction> transactions = fundPurchaseTransactionMapper.selectAllFundPuchaseTransactionWithNullNavAndShare();
        for (FundPurchaseTransaction transaction : transactions) {
            if (transaction.getNav() == null || transaction.getShare() == null) {
                String code = transaction.getCode();
                String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
                if (navStr != null && !navStr.equals("")) {
                    BigDecimal amount = transaction.getAmount();
                    BigDecimal fee = transaction.getFee();
                    BigDecimal share = FinancialCalculationUtil.calculateShare(amount, fee, navStr);
                    transaction.setNav(new BigDecimal(navStr));
                    transaction.setShare(share);
                    fundPurchaseTransactionMapper.updateNavAndShareForFundPurchaseTransaction(transaction);
                    updateNavAndShareForFundTransaction();
                }
            }
        }
    }

    /**
     * @author sichu huang
     * @date 2024/03/18
     **/
    @Override
    public void updateNavAndShareForFundTransaction() {
        List<FundTransaction> transactions = fundTransactionMapper.selectAllFundTransactionWithNullNavAndShare();
        for (FundTransaction transaction : transactions) {
            if (transaction.getNav() == null || transaction.getShare() == null) {
                String code = transaction.getCode();
                String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
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
     * @date 2024/03/20
     **/
    @Override
    public void updateHeldDaysAndUpdateDateForFundPosition(Date date) throws ParseException {
        List<FundPosition> fundPositions = fundPositionMapper.selectAllFundPosition();
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
    public void updateStatusForTransactionInTransit(Date date) throws IOException {
        /* update table fund_purchase_transaction */
        List<FundPurchaseTransaction> fundPurchaseTransactions =
            fundPurchaseTransactionMapper.selectAllFundPurchaseTransactionsByStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
        for (FundPurchaseTransaction transaction : fundPurchaseTransactions) {
            if (date.getTime() >= transaction.getSettlementDate().getTime()) {
                transaction.setStatus(FundTransactionStatus.HELD.getCode());
                /* insert new held transaction into fund_position table */
                insertFundPositionByFundPurchaseTransaction(transaction);
                fundPurchaseTransactionMapper.updateStatusForFundPurchaseTransaction(transaction);
            }
        }
        // TODO: update table fund_redemption_transaction
        /* update table fund_transaction */
        List<FundTransaction> fundTransactions = fundTransactionMapper.selectAllFundTransactionsInTransit();
        for (FundTransaction transaction : fundTransactions) {
            if (date.getTime() >= transaction.getSettlementDate().getTime()) {
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.HELD.getCode());
                    fundTransactionMapper.updateStatusForFundTransaction(transaction);
                }
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
                    fundTransactionMapper.updateStatusForFundTransaction(transaction);
                }
            }
        }
    }

    /**
     * @param purchaseTransaction purchaseTransaction
     * @return cn.sichu.entity.FundPosition
     * @author sichu huang
     * @date 2024/03/22
     **/
    private FundPosition initFundPositionFromPurchaseTransaction(FundPurchaseTransaction purchaseTransaction) throws IOException {
        FundPosition fundPosition = new FundPosition();
        fundPosition.setCode(purchaseTransaction.getCode());
        fundPosition.setTransactionDate(purchaseTransaction.getTransactionDate());
        fundPosition.setInitiationDate(purchaseTransaction.getSettlementDate());
        Date currentDate = new Date();
        long heldDays = TransactionDayUtil.getHeldTransactionDays(currentDate, purchaseTransaction.getTransactionDate());
        fundPosition.setHeldDays((int)heldDays);
        fundPosition.setUpdateDate(currentDate);
        return fundPosition;
    }

    /**
     * 配置 totalAmount. totalPurchaseFee, heldShare, 并插入数据
     *
     * @param fundPosition fundPosition
     * @param amount       amount
     * @param fee          fee
     * @param share        share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void setFundPositionDataAndInsert(FundPosition fundPosition, BigDecimal amount, BigDecimal fee, BigDecimal share) {
        fundPosition.setTotalAmount(amount);
        fundPosition.setTotalPurchaseFee(fee);
        fundPosition.setHeldShare(share);
        fundPositionMapper.insertFundPosition(fundPosition);
    }

    /**
     * 直接插入数据, 并更新之后的数据
     *
     * @param fundPosition fundPosition
     * @param amount       amount
     * @param fee          fee
     * @param share        share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void handleFundPositionBeforeTransactionDate(FundPosition fundPosition, BigDecimal amount, BigDecimal fee, BigDecimal share) {
        setFundPositionDataAndInsert(fundPosition, amount, fee, share);
        updateLaterPositions(fundPosition, amount, fee, share);
    }

    /**
     * 若存在相同日期数据: 获取同日期最大持仓数据, 累加计算后插入数据, 并更新之后的数据
     * <p/>
     * 若不存在相同日期数据: 获取之前最大持仓数据, 累加计算后插入数据, 并更新之后的数据
     *
     * @param fundPosition fundPosition
     * @param amount       amount
     * @param fee          fee
     * @param share        share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void handleFundPositionAfterTransactionDate(FundPosition fundPosition, BigDecimal amount, BigDecimal fee, BigDecimal share) {
        FundPosition lastPosition = fundPositionMapper.selectLastFundPositionInDifferentDate(fundPosition).get(0);
        List<FundPosition> sameDatePosition = fundPositionMapper.selectLastFundPositionInSameDate(fundPosition);
        if (!sameDatePosition.isEmpty()) {
            FundPosition maxSameDatePosition = sameDatePosition.get(0);
            setFundPositionDataAndInsert(fundPosition, maxSameDatePosition.getTotalAmount().add(amount),
                maxSameDatePosition.getTotalPurchaseFee().add(fee), maxSameDatePosition.getHeldShare().add(share));
        } else {
            setFundPositionDataAndInsert(fundPosition, lastPosition.getTotalAmount().add(amount), lastPosition.getTotalPurchaseFee().add(fee),
                lastPosition.getHeldShare().add(share));
        }
        updateLaterPositions(fundPosition, amount, fee, share);
    }

    /**
     * 获取同日期最大持仓数据, 累加计算后插入数据, 并更新之后的数据
     *
     * @param fundPosition fundPosition
     * @param amount       amount
     * @param fee          fee
     * @param share        share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void handleFundPositionEqualsTransactionDate(FundPosition fundPosition, BigDecimal amount, BigDecimal fee, BigDecimal share) {
        FundPosition maxSameDatePosition = fundPositionMapper.selectLastFundPositionInSameDate(fundPosition).get(0);
        setFundPositionDataAndInsert(fundPosition, maxSameDatePosition.getTotalAmount().add(amount),
            maxSameDatePosition.getTotalPurchaseFee().add(fee), maxSameDatePosition.getHeldShare().add(share));
        updateLaterPositions(fundPosition, amount, fee, share);
    }

    /**
     * 更新之后的数据
     *
     * @param fundPosition fundPosition
     * @param amount       amount
     * @param fee          fee
     * @param share        share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void updateLaterPositions(FundPosition fundPosition, BigDecimal amount, BigDecimal fee, BigDecimal share) {
        List<FundPosition> laterPositions = fundPositionMapper.selectFundPositionByCodeAndAfterTransactionDate(fundPosition);
        for (FundPosition position : laterPositions) {
            position.setTotalAmount(position.getTotalAmount().add(amount));
            position.setTotalPurchaseFee(position.getTotalPurchaseFee().add(fee));
            position.setHeldShare(position.getHeldShare().add(share));
            fundPositionMapper.updateTotalAmountAndTotalPurchaseFeeAndHeldShareForFundPosition(position);
        }
    }

}
