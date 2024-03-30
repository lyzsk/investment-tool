package cn.sichu.service.impl;

import cn.sichu.entity.*;
import cn.sichu.enums.FundTransactionStatus;
import cn.sichu.enums.FundTransactionType;
import cn.sichu.exception.FundTransactionException;
import cn.sichu.mapper.*;
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
import java.util.*;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
@Service
public class FundTransactionServiceImpl implements IFundTransactionService {
    @Autowired
    FundInformationServiceImpl fundInformationService;
    @Autowired
    IFundHistoryNavService fundHistoryNavService;
    @Autowired
    FundTransactionMapper fundTransactionMapper;
    @Autowired
    FundPurchaseTransactionMapper fundPurchaseTransactionMapper;
    @Autowired
    FundPurchaseFeeRateMapper fundPurchaseFeeRateMapper;
    @Autowired
    FundRedemptionTransactionMapper fundRedemptionTransactionMapper;
    @Autowired
    FundRedemptionFeeRateMapper fundRedemptionFeeRateMapper;
    @Autowired
    FundPositionMapper fundPositionMapper;
    @Autowired
    FundHistoryPositionMapper fundHistoryPositionMapper;

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
        /* set confirmationDate */
        transaction.setConfirmationDate(transactionDate);
        /* set settlementDate */
        List<FundInformation> fundInformationList = fundInformationService.selectFundPurchaseTransactionProcessByCode(code);
        if (fundInformationList.isEmpty()) {
            throw new FundTransactionException(999, "未查到交易规则");
        }
        FundInformation information = fundInformationList.get(0);
        Integer n = information.getPurchaseConfirmationProcess();
        Date settlementDate = TransactionDayUtil.getNextNTransactionDate(transactionDate, n);
        transaction.setSettlementDate(settlementDate);
        /* set status */
        if (currentDate.getTime() < settlementDate.getTime()) {
            transaction.setStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
        } else {
            transaction.setStatus(FundTransactionStatus.HELD.getCode());
        }
        /* set fee */
        List<FundPurchaseFeeRate> fundPurchaseFeeRates = fundPurchaseFeeRateMapper.selectFundPurchaseFeeRateByConditions(code, tradingPlatform);
        if (fundPurchaseFeeRates.isEmpty()) {
            throw new FundTransactionException(999, "未查到申购费率");
        }
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
        /* set nav, share */
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
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

    @Override
    public void insertFundRedemptionTransactionByConditions(String code, Date applicationDate, BigDecimal share, String tradingPlatform)
        throws ParseException, IOException {
        Date currentDate = new Date();
        FundRedemptionTransaction transaction = new FundRedemptionTransaction();
        /* set 1.code, 2.application_date, 9.share, 10.trading_platform for `fund_redemption_transaction` */
        transaction.setCode(code);
        transaction.setApplicationDate(applicationDate);
        transaction.setShare(share);
        transaction.setTradingPlatform(tradingPlatform);
        /* set 3.transactionDate for `fund_redemption_transaction` */
        Date transactionDate =
            TransactionDayUtil.isTransactionDate(applicationDate) ? applicationDate : TransactionDayUtil.getNextTransactionDate(applicationDate);
        transaction.setTransactionDate(transactionDate);
        /* set 4.confirmationDate, 5.settlementDate for `fund_redemption_transaction` */
        List<FundInformation> fundInformationList = fundInformationService.selectFundRedemptionTransactionProcessByCode(code);
        if (fundInformationList.isEmpty()) {
            throw new FundTransactionException(999, "selectFundRedemptionTransactionProcessByCode 为空");
        }
        FundInformation information = fundInformationList.get(0);
        Integer n = information.getRedemptionConfirmationProcess();
        Date confirmationDate = TransactionDayUtil.getNextNTransactionDate(transactionDate, n);
        transaction.setConfirmationDate(confirmationDate);
        Integer m = information.getRedemptionSettlementProcess();
        Date settlementDate = TransactionDayUtil.getNextNTransactionDate(transactionDate, m);
        transaction.setSettlementDate(settlementDate);
        List<FundPosition> fundPositions = fundPositionMapper.selectAllFundPositionByCodeOrderByTransactionDate(code);
        for (int i = 0; i < fundPositions.size(); i++) {
            FundPosition fundPosition = fundPositions.get(i);
            if (transactionDate.before(fundPositions.get(fundPositions.size() - 1).getInitiationDate())) {
                throw new FundTransactionException(999, "赎回操作应在开始持仓之后");
            }
            if (share.compareTo(fundPositions.get(fundPositions.size() - 1).getHeldShare()) > 0) {
                throw new FundTransactionException(999, "赎回份额超过持仓份额");
            }
            /* update held days for fund_position, 防止定时任务之后启动导致 held_days, update_date 数据不准确 */
            long heldDays = TransactionDayUtil.getHeldDays(fundPosition.getTransactionDate(), transaction.getTransactionDate());
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(transaction.getTransactionDate());
            fundPositionMapper.updateHeldDaysAndUpdateDate(fundPosition);
            /* set 12.mark for `fund_redemption_transaction` */
            if (i == fundPositions.size() - 1) {
                transaction.setMark(DateUtil.dateToStr(fundPositions.get(0).getTransactionDate()) + "->" + DateUtil.dateToStr(transactionDate));
            }
            /* set 11.status for `fund_redemption_transaction` */
            if (currentDate.before(settlementDate)) {
                transaction.setStatus(FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
            } else {
                transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
            }
            /* 查询nav, 若不为空则根据 `fund_position` 的数据配置 `fund_history_position`, `fund_redemption_transaction` */
            String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
            if (navStr != null && !navStr.equals("")) {
                setFundHistoryPositionAndFundRedemptionTransactionData(fundPositions, transaction, i, navStr);
            }
        }
        /* insert `fund_redemption_transaction` */
        fundRedemptionTransactionMapper.insertFundRedemptionTransaction(transaction);
        /* insert `fund_transaction` */
        insertFundTransactionByFundRedemptionTransaction(transaction);
    }

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

    @Override
    public List<FundTransaction> selectAllFundTransactions() {
        return fundTransactionMapper.selectAllFundTransaction();
    }

    @Override
    public void updateNavAndShareForFundPurchaseTransaction() throws ParseException, IOException {
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
                    fundPurchaseTransactionMapper.updateNavAndShare(transaction);
                    updateNavAndShareForFundTransaction();
                }
            }
        }
    }

    @Override
    public void updateNavAndFeeAndAmountForFundRedemptionTransaction() throws ParseException, IOException {
        List<FundRedemptionTransaction> transactions = fundRedemptionTransactionMapper.selectAllFundRedemptionTransactionWithNullNavAndAmount();
        for (FundRedemptionTransaction transaction : transactions) {
            if (transaction.getNav() == null || transaction.getFee() == null || transaction.getAmount() == null) {
                String code = transaction.getCode();
                String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
                if (navStr == null || navStr.equals("")) {
                    continue;
                }
                List<FundRedemptionFeeRate> fundRedemptionFeeRates =
                    fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(code, transaction.getTradingPlatform());
                if (fundRedemptionFeeRates.isEmpty()) {
                    throw new FundTransactionException(999, "未查到赎回费率");
                }
                BigDecimal[] redemptionFeeAndAmount = calculateRedemptionFeeAndAmount(transaction, navStr, fundRedemptionFeeRates);
                transaction.setNav(new BigDecimal(navStr));
                transaction.setFee(redemptionFeeAndAmount[0]);
                transaction.setAmount(redemptionFeeAndAmount[1]);
                fundRedemptionTransactionMapper.updateNavAndFeeAndAmount(transaction);
                updateNavAndFeeAndAmountForFundTransaction();
            }
        }
    }

    @Override
    public void updateHeldDaysAndUpdateDateForFundPosition(Date date) throws ParseException {
        List<FundPosition> fundPositions = fundPositionMapper.selectAllFundPosition();
        for (FundPosition fundPosition : fundPositions) {
            long heldDays = TransactionDayUtil.getHeldDays(fundPosition.getTransactionDate(), date);
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(DateUtil.formatDate(date));
            fundPositionMapper.updateHeldDaysAndUpdateDate(fundPosition);
        }
    }

    @Override
    public void updateStatusForTransactionInTransit(Date date) throws IOException, ParseException {
        /* update `fund_purchase_transaction` */
        List<FundPurchaseTransaction> fundPurchaseTransactions =
            fundPurchaseTransactionMapper.selectAllFundPurchaseTransactionsByStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
        for (FundPurchaseTransaction transaction : fundPurchaseTransactions) {
            if (date.getTime() >= transaction.getSettlementDate().getTime()) {
                transaction.setStatus(FundTransactionStatus.HELD.getCode());
                fundPurchaseTransactionMapper.updateStatus(transaction);
                /* insert HELD transaction into `fund_position` */
                insertFundPositionByFundPurchaseTransaction(transaction);
            }
        }
        /* update `fund_redemption_transaction` */
        List<FundRedemptionTransaction> fundRedemptionTransactions =
            fundRedemptionTransactionMapper.selectAllFundRedemptionTransactionByStatus(FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
        for (FundRedemptionTransaction transaction : fundRedemptionTransactions) {
            if (date.getTime() >= transaction.getConfirmationDate().getTime()) {
                updateFundRedemptionTransactionAfterConfirmation(transaction);
            }
            if (date.getTime() >= transaction.getSettlementDate().getTime()) {
                transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
                fundRedemptionTransactionMapper.updateStatus(transaction);
                insertFundHistoryPositionAndDeleteFundPosition(transaction);
            }
        }
        /* update table fund_transaction */
        List<FundTransaction> fundTransactions = fundTransactionMapper.selectAllFundTransactionInTransit();
        for (FundTransaction transaction : fundTransactions) {
            if (date.getTime() >= transaction.getSettlementDate().getTime()) {
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.HELD.getCode());
                    fundTransactionMapper.updateStatus(transaction);
                }
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
                    fundTransactionMapper.updateStatus(transaction);
                }
            }
        }
    }

    /**
     * @param fundRedemptionTransaction FundRedemptionTransaction
     * @author sichu huang
     * @date 2024/03/24
     **/
    private void insertFundTransactionByFundRedemptionTransaction(FundRedemptionTransaction fundRedemptionTransaction) {
        FundTransaction fundTransaction = new FundTransaction();
        fundTransaction.setCode(fundRedemptionTransaction.getCode());
        fundTransaction.setApplicationDate(fundRedemptionTransaction.getApplicationDate());
        fundTransaction.setTransactionDate(fundRedemptionTransaction.getTransactionDate());
        fundTransaction.setConfirmationDate(fundRedemptionTransaction.getConfirmationDate());
        fundTransaction.setSettlementDate(fundRedemptionTransaction.getSettlementDate());
        fundTransaction.setAmount(fundRedemptionTransaction.getAmount());
        fundTransaction.setFee(fundRedemptionTransaction.getFee());
        fundTransaction.setNav(fundRedemptionTransaction.getNav());
        fundTransaction.setShare(fundRedemptionTransaction.getShare());
        fundTransaction.setTradingPlatform(fundRedemptionTransaction.getTradingPlatform());
        fundTransaction.setStatus(fundRedemptionTransaction.getStatus());
        fundTransaction.setMark(fundRedemptionTransaction.getMark());
        fundTransaction.setType(FundTransactionType.REDEMPTION.getCode());
        fundTransactionMapper.insertFundTransaction(fundTransaction);
    }

    /**
     * @param fundPurchaseTransaction FundPurchaseTransaction
     * @author sichu huang
     * @date 2024/03/21
     **/
    private void insertFundTransactionByFundPurchaseTransaction(FundPurchaseTransaction fundPurchaseTransaction) {
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
        fundTransaction.setMark(fundPurchaseTransaction.getMark());
        fundTransaction.setType(FundTransactionType.PURCHASE.getCode());
        fundTransactionMapper.insertFundTransaction(fundTransaction);
    }

    /**
     * @param purchaseTransaction FundPurchaseTransaction
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
            fundPositionMapper.updateTotalAmountAndTotalPurchaseFeeAndHeldShare(position);
        }
    }

    /**
     * set <b>6.amount, 7.fee, 8.nav</b> for `fund_redemption_transaction`;
     * <br/>
     * set <b>1.code, 2.transaction_date, 3.initiation_date, 4.redemption_date, 5.total_amount, 6.total_purchase_fee,
     * 7.total_redemption_fee, 8.held_share, 9.held_days, 10.mark</b> for `fund_history_position`;
     * <br/>
     * if REDEEMED, insert data into `fund_history_position` and delete `fund_position` data
     *
     * @param fundPositions FundPosition ArrayList
     * @param transaction   FundRedemptionTransaction
     * @param i             i
     * @param navStr        navStr
     * @author sichu huang
     * @date 2024/03/28
     **/
    private void setFundHistoryPositionAndFundRedemptionTransactionData(List<FundPosition> fundPositions, FundRedemptionTransaction transaction,
        int i, String navStr) {
        FundPosition fundPosition = fundPositions.get(i);
        FundHistoryPosition fundHistoryPosition = new FundHistoryPosition();
        /* set 1.code, 2.transactionDate, 3.initiationDate, 4.redemptionDate, 6.totalPurchaseFee, 8.heldShare, 9.heldDays, 10.mark */
        setFundHistoryPositionData(fundHistoryPosition, fundPosition, transaction);
        /* set 7.total_redemption_fee, 5.total_amount */
        List<FundRedemptionFeeRate> fundRedemptionFeeRates =
            fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(transaction.getCode(), transaction.getTradingPlatform());
        if (fundRedemptionFeeRates.isEmpty()) {
            throw new FundTransactionException(999, "未查到赎回费率");
        }
        Map<String, BigDecimal> map = calculateRedemptionFeeAndAmount(fundPosition, navStr, fundRedemptionFeeRates);
        fundHistoryPosition.setTotalRedemptionFee(map.get("fee"));
        fundHistoryPosition.setTotalAmount(map.get("amount"));
        /* set nav, redemption_fee, amount */
        if (i == fundPositions.size() - 1) {
            transaction.setNav(new BigDecimal(navStr));
            transaction.setFee(fundHistoryPosition.getTotalRedemptionFee());
            transaction.setAmount(fundHistoryPosition.getTotalAmount());
        }
        /* insert data into `fund_history_position` and delete `fund_position` data */
        if (transaction.getStatus().equals(FundTransactionStatus.REDEEMED.getCode())) {
            fundHistoryPositionMapper.insertFundHistoryPosition(fundHistoryPosition);
            fundPositionMapper.deleteFundPosition(fundPosition.getId());
        }
    }

    /**
     * set <b>1.code, 2.transactionDate, 3.initiationDate, 4.redemptionDate, 6.totalPurchaseFee,
     * 8.heldShare, 9.heldDays, 10.mark</b> for `fund_history_position`
     *
     * @param fundHistoryPosition FundHistoryPosition
     * @param fundPosition        FundPosition
     * @param transaction         FundRedemptionTransaction
     * @author sichu huang
     * @date 2024/03/24
     **/
    private void setFundHistoryPositionData(FundHistoryPosition fundHistoryPosition, FundPosition fundPosition,
        FundRedemptionTransaction transaction) {
        fundHistoryPosition.setCode(fundPosition.getCode());
        fundHistoryPosition.setTransactionDate(fundPosition.getTransactionDate());
        fundHistoryPosition.setInitiationDate(fundPosition.getInitiationDate());
        fundHistoryPosition.setRedemptionDate(transaction.getTransactionDate());
        fundHistoryPosition.setTotalPurchaseFee(fundPosition.getTotalPurchaseFee());
        fundHistoryPosition.setHeldShare(fundPosition.getHeldShare());
        fundHistoryPosition.setHeldDays(fundPosition.getHeldDays());
        fundHistoryPosition.setMark(
            DateUtil.dateToStr(fundPosition.getTransactionDate()) + "->" + DateUtil.dateToStr(transaction.getTransactionDate()));
    }

    /**
     * @author sichu huang
     * @date 2024/03/18
     **/
    private void updateNavAndShareForFundTransaction() throws ParseException, IOException {
        List<FundTransaction> transactions = fundTransactionMapper.selectAllFundTransactionWithNullNavAndShareForPurchaseType();
        for (FundTransaction transaction : transactions) {
            if (transaction.getNav() == null || transaction.getShare() == null) {
                String code = transaction.getCode();
                String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
                if (navStr == null || navStr.equals("")) {
                    continue;
                }
                BigDecimal amount = transaction.getAmount();
                BigDecimal fee = transaction.getFee();
                BigDecimal share = FinancialCalculationUtil.calculateShare(amount, fee, navStr);
                transaction.setNav(new BigDecimal(navStr));
                transaction.setShare(share);
                fundTransactionMapper.updateNavAndShare(transaction);
            }
        }
    }

    /**
     * @author sichu huang
     * @date 2024/03/25
     **/
    private void updateNavAndFeeAndAmountForFundTransaction() throws ParseException, IOException {
        List<FundTransaction> transactions = fundTransactionMapper.selectAllFundTransactionWithNullNavAndFeeAndAmountForRedemptionType();
        for (FundTransaction transaction : transactions) {
            if (transaction.getNav() == null || transaction.getFee() == null || transaction.getAmount() == null) {
                String code = transaction.getCode();
                String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transaction.getTransactionDate());
                if (navStr == null || navStr.equals("")) {
                    continue;
                }
                List<FundRedemptionFeeRate> fundRedemptionFeeRates =
                    fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(code, transaction.getTradingPlatform());
                if (fundRedemptionFeeRates.isEmpty()) {
                    throw new FundTransactionException(999, "未查到赎回费率");
                }
                BigDecimal[] redemptionFeeAndAmount = calculateRedemptionFeeAndAmount(transaction, navStr, fundRedemptionFeeRates);
                transaction.setNav(new BigDecimal(navStr));
                transaction.setFee(redemptionFeeAndAmount[0]);
                transaction.setAmount(redemptionFeeAndAmount[1]);
                fundTransactionMapper.updateNavAndFeeAndAmount(transaction);
            }
        }
    }

    /**
     * update 6.amount, 7.fee, 8.nav for `fund_redemption_transaction`
     *
     * @param transaction FundRedemptionTransaction
     * @author sichu huang
     * @date 2024/03/28
     **/
    private void updateFundRedemptionTransactionAfterConfirmation(FundRedemptionTransaction transaction) throws ParseException, IOException {
        String code = transaction.getCode();
        String mark = transaction.getMark();
        Date transactionDate = transaction.getTransactionDate();
        /* set 8.nav */
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
        if (navStr == null || navStr.equals("")) {
            throw new FundTransactionException(999, "未查到净值");
        }
        transaction.setNav(new BigDecimal(navStr));
        long heldDays = TransactionDayUtil.getHeldDays(mark);
        List<FundPosition> fundPositions =
            fundPositionMapper.selectAllFundPositionByConditionsOrderByTransactionDate(code, (int)heldDays, transactionDate);
        for (int i = 0; i < fundPositions.size(); i++) {
            FundPosition fundPosition = fundPositions.get(i);
            List<FundRedemptionFeeRate> fundRedemptionFeeRates =
                fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(transaction.getCode(), transaction.getTradingPlatform());
            if (fundRedemptionFeeRates.isEmpty()) {
                throw new FundTransactionException(999, "未查到赎回费率");
            }
            Map<String, BigDecimal> map = calculateRedemptionFeeAndAmount(fundPosition, navStr, fundRedemptionFeeRates);
            /* set 7.fee, 6.amount */
            if (i == fundPositions.size() - 1) {
                transaction.setFee(map.get("fee"));
                transaction.setAmount(map.get("amount"));
            }
        }
        fundRedemptionTransactionMapper.updateNavAndFeeAndAmount(transaction);
    }

    /**
     * @param transaction FundRedemptionTransaction
     * @author sichu huang
     * @date 2024/03/30
     **/
    private void insertFundHistoryPositionAndDeleteFundPosition(FundRedemptionTransaction transaction) throws ParseException, IOException {
        String code = transaction.getCode();
        String mark = transaction.getMark();
        Date transactionDate = transaction.getTransactionDate();
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
        if (navStr == null || navStr.equals("")) {
            throw new FundTransactionException(999, "未查到净值");
        }
        long heldDays = TransactionDayUtil.getHeldDays(mark);
        List<FundPosition> fundPositions =
            fundPositionMapper.selectAllFundPositionByConditionsOrderByTransactionDate(code, (int)heldDays, transactionDate);
        for (FundPosition fundPosition : fundPositions) {
            FundHistoryPosition fundHistoryPosition = new FundHistoryPosition();
            /* set 1.code, 2.transactionDate, 3.initiationDate, 4.redemptionDate, 6.totalPurchaseFee, 8.heldShare, 9.heldDays, 10.mark */
            setFundHistoryPositionData(fundHistoryPosition, fundPosition, transaction);
            /* set 7.total_redemption_fee, 5.total_amount */
            List<FundRedemptionFeeRate> fundRedemptionFeeRates =
                fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(transaction.getCode(), transaction.getTradingPlatform());
            if (fundRedemptionFeeRates.isEmpty()) {
                throw new FundTransactionException(999, "未查到赎回费率");
            }
            Map<String, BigDecimal> map = calculateRedemptionFeeAndAmount(fundPosition, navStr, fundRedemptionFeeRates);
            fundHistoryPosition.setTotalRedemptionFee(map.get("fee"));
            fundHistoryPosition.setTotalAmount(map.get("amount"));
            /* insert data into `fund_history_position` and delete `fund_position` data */
            if (transaction.getStatus().equals(FundTransactionStatus.REDEEMED.getCode())) {
                fundHistoryPositionMapper.insertFundHistoryPosition(fundHistoryPosition);
                fundPositionMapper.deleteFundPosition(fundPosition.getId());
            }
        }
    }

    /**
     * 返回 K = "fee", "amount", V = fee累加值, amount累加值 的哈希表
     *
     * @param fundPosition           FundPosition
     * @param navStr                 navStr
     * @param fundRedemptionFeeRates FundRedemptionFeeRate List
     * @return java.util.Map<java.lang.String, java.math.BigDecimal>
     * @author sichu huang
     * @date 2024/03/30
     **/
    private Map<String, BigDecimal> calculateRedemptionFeeAndAmount(FundPosition fundPosition, String navStr,
        List<FundRedemptionFeeRate> fundRedemptionFeeRates) {
        Map<String, BigDecimal> map = new HashMap<>();
        for (int i = 0; i < fundRedemptionFeeRates.size(); i++) {
            FundRedemptionFeeRate fundRedemptionFeeRate = fundRedemptionFeeRates.get(i);
            String feeRate = fundRedemptionFeeRate.getFeeRate();
            if (fundPosition.getHeldDays() < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                map.put("fee", FinancialCalculationUtil.calculateRedemptionFee(fundPosition.getHeldShare(), navStr, feeRate));
                map.put("amount", FinancialCalculationUtil.calculateRedemptionAmount(fundPosition.getHeldShare(), navStr, map.get("fee")));
                break;
            }
            if (i > 0 && fundPosition.getHeldDays() >= fundRedemptionFeeRates.get(i - 1).getFeeRateChangeDays()
                && fundPosition.getHeldDays() < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                map.put("fee", FinancialCalculationUtil.calculateRedemptionFee(fundPosition.getHeldShare(), navStr, feeRate));
                map.put("amount", FinancialCalculationUtil.calculateRedemptionAmount(fundPosition.getHeldShare(), navStr, map.get("fee")));
                break;
            }
            if (i == fundRedemptionFeeRates.size() - 1 && fundPosition.getHeldDays() >= fundRedemptionFeeRate.getFeeRateChangeDays()) {
                feeRate = "0.00%";
                map.put("fee", FinancialCalculationUtil.calculateRedemptionFee(fundPosition.getHeldShare(), navStr, feeRate));
                map.put("amount", FinancialCalculationUtil.calculateRedemptionAmount(fundPosition.getHeldShare(), navStr, map.get("fee")));
                break;
            }
        }
        return map;
    }

    /**
     * 返回 BigDecimal[] array with length = 2, BigDecimal[0] = redemptionFee, BigDecimal[1] = amount
     *
     * @param transaction            FundRedemptionTransaction
     * @param navStr                 navStr
     * @param fundRedemptionFeeRates FundRedemptionFeeRate List
     * @return java.math.BigDecimal[]
     * @author sichu huang
     * @date 2024/03/30
     **/
    private BigDecimal[] calculateRedemptionFeeAndAmount(FundRedemptionTransaction transaction, String navStr,
        List<FundRedemptionFeeRate> fundRedemptionFeeRates) throws ParseException {
        BigDecimal[] redemptionFeeAndAmount = new BigDecimal[2];
        long heldDays = TransactionDayUtil.getHeldDays(transaction.getMark());
        BigDecimal share = transaction.getShare();
        BigDecimal fee = null;
        BigDecimal amount = null;
        for (int i = 0; i < fundRedemptionFeeRates.size(); i++) {
            FundRedemptionFeeRate fundRedemptionFeeRate = fundRedemptionFeeRates.get(i);
            String feeRate = fundRedemptionFeeRate.getFeeRate();
            if (heldDays < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                fee = FinancialCalculationUtil.calculateRedemptionFee(share, navStr, feeRate);
                amount = FinancialCalculationUtil.calculateRedemptionAmount(share, navStr, fee);
                break;
            }
            if (i > 0 && heldDays >= fundRedemptionFeeRates.get(i - 1).getFeeRateChangeDays()
                && heldDays < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                fee = FinancialCalculationUtil.calculateRedemptionFee(share, navStr, feeRate);
                amount = FinancialCalculationUtil.calculateRedemptionAmount(share, navStr, fee);
                break;
            }
            if (i == fundRedemptionFeeRates.size() - 1 && heldDays > fundRedemptionFeeRate.getFeeRateChangeDays()) {
                feeRate = "0.00%";
                fee = FinancialCalculationUtil.calculateRedemptionFee(share, navStr, feeRate);
                amount = FinancialCalculationUtil.calculateRedemptionAmount(share, navStr, fee);
                break;
            }
        }
        redemptionFeeAndAmount[0] = fee;
        redemptionFeeAndAmount[1] = amount;
        return redemptionFeeAndAmount;
    }

    /**
     * 返回 BigDecimal[] array with length = 2, BigDecimal[0] = redemptionFee, BigDecimal[1] = amount
     *
     * @param transaction            FundTransaction
     * @param navStr                 navStr
     * @param fundRedemptionFeeRates FundRedemptionFeeRate List
     * @return java.math.BigDecimal[]
     * @author sichu huang
     * @date 2024/03/30
     **/
    private BigDecimal[] calculateRedemptionFeeAndAmount(FundTransaction transaction, String navStr,
        List<FundRedemptionFeeRate> fundRedemptionFeeRates) throws ParseException {
        BigDecimal[] redemptionFeeAndAmount = new BigDecimal[2];
        long heldDays = TransactionDayUtil.getHeldDays(transaction.getMark());
        BigDecimal share = transaction.getShare();
        BigDecimal fee = null;
        BigDecimal amount = null;
        for (int i = 0; i < fundRedemptionFeeRates.size(); i++) {
            FundRedemptionFeeRate fundRedemptionFeeRate = fundRedemptionFeeRates.get(i);
            String feeRate = fundRedemptionFeeRate.getFeeRate();
            if (heldDays < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                fee = FinancialCalculationUtil.calculateRedemptionFee(share, navStr, feeRate);
                amount = FinancialCalculationUtil.calculateRedemptionAmount(share, navStr, fee);
                break;
            }
            if (i > 0 && heldDays >= fundRedemptionFeeRates.get(i - 1).getFeeRateChangeDays()
                && heldDays < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                fee = FinancialCalculationUtil.calculateRedemptionFee(share, navStr, feeRate);
                amount = FinancialCalculationUtil.calculateRedemptionAmount(share, navStr, fee);
                break;
            }
            if (i == fundRedemptionFeeRates.size() - 1 && heldDays > fundRedemptionFeeRate.getFeeRateChangeDays()) {
                feeRate = "0.00%";
                fee = FinancialCalculationUtil.calculateRedemptionFee(share, navStr, feeRate);
                amount = FinancialCalculationUtil.calculateRedemptionAmount(share, navStr, fee);
                break;
            }
        }
        redemptionFeeAndAmount[0] = fee;
        redemptionFeeAndAmount[1] = amount;
        return redemptionFeeAndAmount;
    }
}
