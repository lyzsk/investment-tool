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
    @Autowired
    FundDividendTransactionMapper fundDividendTransactionMapper;

    @Override
    public void purchaseFund(String code, Date applicationDate, BigDecimal amount, String tradingPlatform) throws IOException, ParseException {
        Date currentDate = new Date();
        FundTransaction transaction = new FundTransaction();
        /* set 1.code, 2.application_date, 3.amount, 4.trading_platform, 5.type */
        transaction.setCode(code);
        transaction.setApplicationDate(applicationDate);
        transaction.setAmount(amount);
        transaction.setTradingPlatform(tradingPlatform);
        transaction.setType(FundTransactionType.PURCHASE.getCode());
        /* calculate and set 6.transaction_date, 7.confirmation_date, 8.settlement_date */
        Date transactionDate =
            TransactionDayUtil.isTransactionDate(applicationDate) ? applicationDate : TransactionDayUtil.getNextTransactionDate(applicationDate);
        transaction.setTransactionDate(transactionDate);
        transaction.setConfirmationDate(transactionDate);
        List<FundInformation> informationList = fundInformationService.selectFundPurchaseTransactionProcessByCode(code);
        if (informationList.isEmpty()) {
            throw new FundTransactionException(999,
                "can't calculate purchase transaction's settlement_date, because no fund information found according to this code");
        }
        FundInformation information = informationList.get(0);
        Integer n = information.getPurchaseConfirmationProcess();
        Date settlementDate = TransactionDayUtil.getNextNTransactionDate(transactionDate, n);
        transaction.setSettlementDate(settlementDate);
        /* set 9.status */
        if (currentDate.before(settlementDate)) {
            transaction.setStatus(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode());
        } else {
            transaction.setStatus(FundTransactionStatus.HELD.getCode());
        }
        /* set 10.fee */
        List<FundPurchaseFeeRate> feeRateList = fundPurchaseFeeRateMapper.selectFundPurchaseFeeRateByConditions(code, tradingPlatform);
        if (feeRateList.isEmpty()) {
            throw new FundTransactionException(999,
                "can't calculate purchase transaction's fee, because no fee rate found according to this code and trading_platform");
        }
        for (int i = 0; i < feeRateList.size(); i++) {
            FundPurchaseFeeRate fundPurchaseFeeRate = feeRateList.get(i);
            String feeRate = fundPurchaseFeeRate.getFeeRate();
            if (!feeRate.endsWith("%")) {
                transaction.setFee(new BigDecimal(feeRate));
                break;
            }
            if (amount.compareTo(new BigDecimal(fundPurchaseFeeRate.getFeeRateChangeAmount())) < 0) {
                transaction.setFee(FinancialCalculationUtil.calculatePurchaseFee(amount, feeRate));
                break;
            }
            if (i > 0 && amount.compareTo(new BigDecimal(feeRateList.get(i - 1).getFeeRateChangeAmount())) >= 0
                && amount.compareTo(new BigDecimal(feeRateList.get(i).getFeeRateChangeAmount())) < 0) {
                transaction.setFee(FinancialCalculationUtil.calculatePurchaseFee(amount, feeRate));
                break;
            }
        }
        /* set 11.nav, 12.share, optional, only if nav is updated */
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
        if (navStr != null && !navStr.equals("")) {
            transaction.setNav(new BigDecimal(navStr));
            transaction.setShare(FinancialCalculationUtil.calculateShare(amount, transaction.getFee(), navStr));
            /* insert fund_position table */
            if (Objects.equals(transaction.getStatus(), FundTransactionStatus.HELD.getCode())) {
                insertFundPositionByFundPurchaseTransaction(transaction);
            }
        }
        /* insert `fund_transaction` */
        fundTransactionMapper.insertFundTransaction(transaction);
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
            fundPositionMapper.updateTotalAmountAndHeldDaysAndUpdateDate(fundPosition);
            /* set 12.mark for `fund_redemption_transaction` */
            if (i == fundPositions.size() - 1) {
                Date firstTransactionDate = fundPositions.get(0).getTransactionDate();
                String mark = DateUtil.dateToStr(firstTransactionDate) + "->" + DateUtil.dateToStr(transactionDate);
                transaction.setMark(mark);
                fundPurchaseTransactionMapper.updateMarkByConditions(code, mark, firstTransactionDate, transactionDate);
                fundTransactionMapper.updateMarkByConditions(code, mark, firstTransactionDate, transactionDate);
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
    public void insertFundDividendTransactionByConditions(String code, Date applicationDate, BigDecimal dividendAmountPerShare,
        String tradingPlatform) {
        FundDividendTransaction transaction = new FundDividendTransaction();
        transaction.setCode(code);
        // TODO: 等遇到现金分红的时候看一下是当天公布当天分红还是隔一天, 还是要解析分红公告
        transaction.setApplicationDate(applicationDate);
        transaction.setTransactionDate(applicationDate);
        transaction.setConfirmationDate(applicationDate);
        transaction.setSettlementDate(applicationDate);
        transaction.setDividendAmountPerShare(dividendAmountPerShare);
        transaction.setStatus(FundTransactionStatus.CASH_DIVIDEND.getCode());
        transaction.setTradingPlatform(tradingPlatform);
        List<FundPosition> fundPositionList = fundPositionMapper.selectFundPositionWithMaxHeldShareByCode(code);
        if (fundPositionList.isEmpty()) {
            throw new FundTransactionException(999, "分红时无持仓");
        }
        BigDecimal heldShare = fundPositionList.get(0).getHeldShare();
        transaction.setAmount(FinancialCalculationUtil.calculateDividendAmount(heldShare, dividendAmountPerShare));
        /* insert `fund_dividend_transaction` */
        fundDividendTransactionMapper.insertFundDividendTransaction(transaction);
        /* insert `fund_transaction` */
        insertFundTransactionByFundDividendTransaction(transaction);
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
    public void updateTotalAmountAndHeldDaysAndUpdateDateForFundPosition(Date date) throws ParseException, IOException {
        List<FundPosition> fundPositions = fundPositionMapper.selectAllFundPosition();
        for (FundPosition fundPosition : fundPositions) {
            Date formattedDate = DateUtil.formatDate(date);
            String navStr = fundHistoryNavService.selectLastNotNullFundHistoryNavByConditions(fundPosition.getCode(), formattedDate);
            fundPosition.setTotalAmount(FinancialCalculationUtil.calculateTotalAmount(fundPosition.getHeldShare(), navStr));
            long heldDays = TransactionDayUtil.getHeldDays(fundPosition.getTransactionDate(), date);
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(formattedDate);
            fundPositionMapper.updateTotalAmountAndHeldDaysAndUpdateDate(fundPosition);
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
     * insert into `fund_position` with:
     * <br/>
     * 1.id, 2.code, 3.transaction_date, 4.initiation_date, 5.redemption_date, 6.total_principal_amount,
     * 7.total_amount, 8.total_purchase_fee, 9.total_redemption_fee, 10.held_share, 11.held_days, 12.update_date,
     * 13.mark
     * <p/>
     * 对于purchase交易, <b>1.id</b> 通过mapper自增; <b>5.redemption_date, 9.total_redemption_fee, 13.mark</b> 必为null
     *
     * @param transaction FundTransaction
     * @author sichu huang
     * @date 2024/03/20
     **/
    private void insertFundPositionByFundPurchaseTransaction(FundTransaction transaction) throws IOException, ParseException {
        String code = transaction.getCode();
        BigDecimal amount = transaction.getAmount();
        BigDecimal fee = transaction.getFee();
        BigDecimal share = transaction.getShare();
        Date transactionDate = transaction.getTransactionDate();
        Date initiationDate = transaction.getSettlementDate();
        FundPosition fundPosition = new FundPosition();
        /* set 1.code, 2.transaction_date, 3.initiation_date, 4.held_days, 5.update_date */
        fundPosition.setCode(code);
        fundPosition.setTransactionDate(transactionDate);
        fundPosition.setInitiationDate(initiationDate);
        Date currentDate = new Date();
        long heldDays = TransactionDayUtil.getHeldTransactionDays(currentDate, transaction.getTransactionDate());
        fundPosition.setHeldDays((int)heldDays);
        fundPosition.setUpdateDate(currentDate);
        /* set 6.total_principal_amount, 7.total_purchase_fee, 8.held_share, 9.total_amount */
        List<FundPosition> fundPositionList = fundPositionMapper.selectAllFundPositionByCodeOrderByTransactionDate(code);
        if (fundPositionList.isEmpty()) {
            /* 若无对应code的持仓数据: 直接插入数据 */
            setFundPositionDataAndInsert(fundPosition, amount, fee, share);
        } else {
            /* 若有对应code的持仓数据: 日期最小的 fundPosition 为参照开始判断 */
            FundPosition position = fundPositionList.get(0);
            if (transaction.getTransactionDate().before(position.getTransactionDate())) {
                handleFundPositionBeforeTransactionDate(fundPosition, amount, fee, share);
            } else if (transaction.getTransactionDate().after(position.getTransactionDate())) {
                handleFundPositionAfterTransactionDate(fundPosition, amount, fee, share);
            } else {
                handleFundPositionEqualsTransactionDate(fundPosition, amount, fee, share);
            }
        }
    }

    /**
     * 首次 HELD 时, 更新的 total_amount 根据 initiation_date 的上一个交易日的 nav 计算
     * <p/>
     * set and insert 6.total_principal_amount, 7.total_purchase_fee, 8.held_share, 9.total_amount into `fund_position`
     *
     * @param fundPosition    fundPosition
     * @param principalAmount principalAmount
     * @param fee             fee
     * @param share           share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void setFundPositionDataAndInsert(FundPosition fundPosition, BigDecimal principalAmount, BigDecimal fee, BigDecimal share)
        throws IOException, ParseException {
        fundPosition.setTotalPrincipalAmount(principalAmount);
        fundPosition.setTotalPurchaseFee(fee);
        fundPosition.setHeldShare(share);
        Date lastNTransactionDate = TransactionDayUtil.getLastNTransactionDate(fundPosition.getInitiationDate(), 1);
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(fundPosition.getCode(), lastNTransactionDate);
        if (navStr == null || navStr.equals("")) {
            throw new FundTransactionException(999,
                "can't calculate total_amount for `fund_position`, because nav is not update before settlement_date/initiation_date");
        }
        fundPosition.setTotalAmount(FinancialCalculationUtil.calculateTotalAmount(share, navStr));
        fundPositionMapper.insertFundPosition(fundPosition);
    }

    /**
     * set and insert 6.total_principal_amount, 7.total_purchase_fee, 8.held_share, 9.total_amount into `fund_position`
     * <p/>
     * update 6.total_principal_amount, 7.total_purchase_fee, 8.held_share, 9.total_amount for `fund_position` (排序之后的所有持仓)
     *
     * @param fundPosition    FundPosition
     * @param principalAmount principalAmount
     * @param fee             fee
     * @param share           share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void handleFundPositionBeforeTransactionDate(FundPosition fundPosition, BigDecimal principalAmount, BigDecimal fee, BigDecimal share)
        throws IOException, ParseException {
        setFundPositionDataAndInsert(fundPosition, principalAmount, fee, share);
        updateLaterPositions(fundPosition, principalAmount, fundPosition.getTotalAmount(), fee, share);
    }

    /**
     * 若存在相同日期数据: 获取同日期最大持仓数据, 累加计算后插入数据, 并更新之后的数据
     * <p/>
     * 若不存在相同日期数据: 获取之前最大持仓数据, 累加计算后插入数据, 并更新之后的数据
     *
     * @param fundPosition    FundPosition
     * @param principalAmount principalAmount
     * @param fee             fee
     * @param share           share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void handleFundPositionAfterTransactionDate(FundPosition fundPosition, BigDecimal principalAmount, BigDecimal fee, BigDecimal share)
        throws IOException, ParseException {
        FundPosition lastPosition = fundPositionMapper.selectLastFundPositionInDifferentDate(fundPosition).get(0);
        List<FundPosition> sameDatePositionList = fundPositionMapper.selectLastFundPositionInSameDate(fundPosition);
        if (!sameDatePositionList.isEmpty()) {
            FundPosition lastSameDatePosition = sameDatePositionList.get(0);
            setFundPositionDataAndInsert(fundPosition, lastSameDatePosition.getTotalPrincipalAmount().add(principalAmount),
                lastSameDatePosition.getTotalPurchaseFee().add(fee), lastSameDatePosition.getHeldShare().add(share));
        } else {
            setFundPositionDataAndInsert(fundPosition, lastPosition.getTotalPrincipalAmount().add(principalAmount),
                lastPosition.getTotalPurchaseFee().add(fee), lastPosition.getHeldShare().add(share));
        }
        updateLaterPositions(fundPosition, principalAmount, fundPosition.getTotalAmount(), fee, share);
    }

    /**
     * 获取同日期最大持仓数据, 累加计算后插入数据, 并更新之后的数据
     *
     * @param fundPosition    FundPosition
     * @param principalAmount principalAmount
     * @param fee             fee
     * @param share           share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void handleFundPositionEqualsTransactionDate(FundPosition fundPosition, BigDecimal principalAmount, BigDecimal fee, BigDecimal share)
        throws IOException, ParseException {
        FundPosition lastSameDatePosition = fundPositionMapper.selectLastFundPositionInSameDate(fundPosition).get(0);
        setFundPositionDataAndInsert(fundPosition, lastSameDatePosition.getTotalPrincipalAmount().add(principalAmount),
            lastSameDatePosition.getTotalPurchaseFee().add(fee), lastSameDatePosition.getHeldShare().add(share));
        updateLaterPositions(fundPosition, principalAmount, fundPosition.getTotalAmount(), fee, share);
    }

    /**
     * update 6.total_principal_amount, 7.total_purchase_fee, 8.held_share, 9.total_amount for `fund_position` (排序之后的所有持仓)
     *
     * @param fundPosition    fundPosition
     * @param principalAmount principalAmount
     * @param totalAmount     totalAmount
     * @param fee             fee
     * @param share           share
     * @author sichu huang
     * @date 2024/03/22
     **/
    private void updateLaterPositions(FundPosition fundPosition, BigDecimal principalAmount, BigDecimal totalAmount, BigDecimal fee,
        BigDecimal share) {
        List<FundPosition> laterPositions = fundPositionMapper.selectFundPositionByCodeAndAfterTransactionDate(fundPosition);
        for (FundPosition position : laterPositions) {
            position.setTotalPrincipalAmount(position.getTotalPrincipalAmount().add(principalAmount));
            position.setTotalPurchaseFee(position.getTotalPurchaseFee().add(fee));
            position.setHeldShare(position.getHeldShare().add(share));
            position.setTotalAmount(position.getTotalAmount().add(totalAmount));
            // TODO: 待验证, 增加了 set total_amount
            fundPositionMapper.updateTotalPrincipalAmountAndTotalPurchaseFeeAndHeldShareAndTotalAmount(position);
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

    private void insertFundTransactionByFundDividendTransaction(FundDividendTransaction fundDividendTransaction) {
        FundTransaction fundTransaction = new FundTransaction();
        fundTransaction.setCode(fundDividendTransaction.getCode());
        fundTransaction.setApplicationDate(fundDividendTransaction.getApplicationDate());
        fundTransaction.setTransactionDate(fundDividendTransaction.getTransactionDate());
        fundTransaction.setConfirmationDate(fundDividendTransaction.getConfirmationDate());
        fundTransaction.setSettlementDate(fundDividendTransaction.getSettlementDate());
        fundTransaction.setAmount(fundDividendTransaction.getAmount());
        fundTransaction.setShare(fundDividendTransaction.getShare());
        fundTransaction.setDividendAmountPerShare(fundDividendTransaction.getDividendAmountPerShare());
        fundTransaction.setTradingPlatform(fundDividendTransaction.getTradingPlatform());
        fundTransaction.setStatus(fundDividendTransaction.getStatus());
        fundTransaction.setType(FundTransactionType.DIVIDEND.getCode());
        fundTransactionMapper.insertFundTransaction(fundTransaction);
    }

    /**
     * set <b>6.amount, 7.fee, 8.nav</b> for `fund_redemption_transaction`;
     * <br/>
     * set <b>1.code, 2.transaction_date, 3.initiation_date, 4.redemption_date, 5.total_principal_amount, 6.total_amount,
     * 7.total_purchase_fee, 8.total_redemption_fee, 9.held_share, 10.held_days, 11.mark</b> for `fund_history_position`;
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
        /* set 1.code, 2.transactionDate, 3.initiationDate, 4.redemptionDate, 5.total_principal_amount, */
        /* 7.totalPurchaseFee, 9.heldShare, 10.heldDays, 11.mark */
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
     * set <b>1.code, 2.transactionDate, 3.initiationDate, 4.redemptionDate, 5.total_principal_amount,
     * 7.totalPurchaseFee, 9.heldShare, 10.heldDays, 11.mark</b> for `fund_history_position`
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
        fundHistoryPosition.setTotalPrincipalAmount(fundPosition.getTotalPrincipalAmount());
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
            /* set 1.code, 2.transactionDate, 3.initiationDate, 4.redemptionDate, 5.total_principal_amount, */
            /* 6.totalPurchaseFee, 8.heldShare, 9.heldDays, 10.mark */
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
        Map<String, BigDecimal> map = new HashMap<>(2);
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
