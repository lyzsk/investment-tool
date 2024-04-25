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
                "can't calculate purchase transaction's settlement_date, because no fund information found by code");
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
        /* set 11.nav, 12.share, optional, only if nav is already updated */
        String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
        if (navStr != null && !navStr.equals("")) {
            transaction.setNav(new BigDecimal(navStr));
            transaction.setShare(FinancialCalculationUtil.calculateShare(amount, transaction.getFee(), navStr));
            /* insert `fund_position` */
            if (Objects.equals(transaction.getStatus(), FundTransactionStatus.HELD.getCode())) {
                insertFundPositionByFundTransaction(transaction);
            }
        }
        /* insert `fund_transaction` */
        fundTransactionMapper.insertFundTransaction(transaction);
    }

    /**
     * insert into `fund_position` with:
     * <br/>
     * 1.id, 2.code, 3.transaction_date, 4.initiation_date, 5.redemption_date, 6.total_principal_amount,
     * 7.total_amount, 8.total_purchase_fee, 9.total_redemption_fee, 10.held_share, 11.held_days, 12.update_date,
     * 13.status, 14.mark
     * <p/>
     * 对于purchase交易, <b>1.id</b> 通过mapper自增; <b>5.redemption_date, 9.total_redemption_fee, 14.mark</b> 必为null
     *
     * @param transaction FundTransaction
     * @author sichu huang
     * @date 2024/03/20
     **/
    private void insertFundPositionByFundTransaction(FundTransaction transaction) throws IOException, ParseException {
        String code = transaction.getCode();
        BigDecimal amount = transaction.getAmount();
        BigDecimal fee = transaction.getFee();
        BigDecimal share = transaction.getShare();
        Date transactionDate = transaction.getTransactionDate();
        Date initiationDate = transaction.getSettlementDate();
        FundPosition fundPosition = new FundPosition();
        /* set 1.code, 2.transaction_date, 3.initiation_date, 4.held_days, 5.update_date, 6.status */
        fundPosition.setCode(code);
        fundPosition.setTransactionDate(transactionDate);
        fundPosition.setInitiationDate(initiationDate);
        Date currentDate = new Date();
        long heldDays = TransactionDayUtil.getHeldTransactionDays(currentDate, transaction.getTransactionDate());
        fundPosition.setHeldDays((int)heldDays);
        fundPosition.setUpdateDate(currentDate);
        fundPosition.setStatus(transaction.getStatus());
        /* set 7.total_principal_amount, 8.total_purchase_fee, 9.held_share, 10.total_amount */
        List<FundPosition> fundPositionList = fundPositionMapper.selectAllFundPositionWithNullMark(code);
        if (fundPositionList.isEmpty()) {
            /* 若无对应code的持仓数据: 直接插入数据 */
            setFundPositionDataAndInsert(fundPosition, amount, fee, share);
        } else {
            /* 若有对应code的持仓数据: 以 transaction_date, held_share 最小的 fundPosition 为参照开始判断 */
            FundPosition position = fundPositionList.get(0);
            if (transaction.getTransactionDate().before(position.getTransactionDate())) {
                handleFundPositionBeforeTransactionDate(fundPosition, amount, fee, share);
            } else {
                handleFundPositionAfterOrEqualsTransactionDate(fundPosition, amount, fee, share);
            }
        }
    }

    /**
     * set and insert 1.total_principal_amount, 2.total_purchase_fee, 3.held_share, 4.total_amount into `fund_position`
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
     * set and insert 1.total_principal_amount, 2.total_purchase_fee, 3.held_share, 4.total_amount into `fund_position`
     * <p/>
     * update 1.total_principal_amount, 2.total_purchase_fee, 3.held_share, 4.total_amount for `fund_position` (排序之后的所有持仓)
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
     * 若存在相同日期数据/不相同日期数据: 获取最大持仓数据, 累加计算后插入数据, 并更新之后的数据
     *
     * @param fundPosition    FundPosition
     * @param principalAmount principalAmount
     * @param fee             fee
     * @param share           share
     * @author sichu huang
     * @date 2024/04/22
     **/
    private void handleFundPositionAfterOrEqualsTransactionDate(FundPosition fundPosition, BigDecimal principalAmount, BigDecimal fee,
        BigDecimal share) throws IOException, ParseException {
        FundPosition lastPosition = fundPositionMapper.selectLastFundPosition(fundPosition).get(0);
        setFundPositionDataAndInsert(fundPosition, lastPosition.getTotalPrincipalAmount().add(principalAmount),
            lastPosition.getTotalPurchaseFee().add(fee), lastPosition.getHeldShare().add(share));
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

    @Override
    public void redeemFund(String code, Date applicationDate, BigDecimal share, String tradingPlatform) throws ParseException, IOException {
        Date currentDate = new Date();
        FundTransaction transaction = new FundTransaction();
        /* set 1.code, 2.application_date, 3.share, 4.trading_platform, 5.type */
        transaction.setCode(code);
        transaction.setApplicationDate(applicationDate);
        transaction.setShare(share);
        transaction.setTradingPlatform(tradingPlatform);
        transaction.setType(FundTransactionType.REDEMPTION.getCode());
        /* calculate and set 6.transactionDate, 7.confirmationDate, 8.settlementDate */
        Date transactionDate =
            TransactionDayUtil.isTransactionDate(applicationDate) ? applicationDate : TransactionDayUtil.getNextTransactionDate(applicationDate);
        transaction.setTransactionDate(transactionDate);
        List<FundInformation> fundInformationList = fundInformationService.selectFundRedemptionTransactionProcessByCode(code);
        if (fundInformationList.isEmpty()) {
            throw new FundTransactionException(999,
                "can't calculate redemption transaction's confirmation_date and settlement_date, because no fund information found by code");
        }
        FundInformation information = fundInformationList.get(0);
        Integer n = information.getRedemptionConfirmationProcess();
        Date confirmationDate = TransactionDayUtil.getNextNTransactionDate(transactionDate, n);
        transaction.setConfirmationDate(confirmationDate);
        Integer m = information.getRedemptionSettlementProcess();
        Date settlementDate = TransactionDayUtil.getNextNTransactionDate(transactionDate, m);
        transaction.setSettlementDate(settlementDate);
        /* set 9.mark, 在 `fund_transaction` 中为一条 redemption, 在 `fund_position` 中为n条 redemption, (仅考虑每笔交易满份额赎回) */
        List<FundPosition> fundPositionList = fundPositionMapper.selectAllFundPositionWithNullMark(code);
        int size = fundPositionList.size();
        BigDecimal heldShare = fundPositionList.get(size - 1).getHeldShare();
        Deque<Date> dateDeque = new ArrayDeque<>();
        List<BigDecimal> feeList = new ArrayList<>();
        List<BigDecimal> amountList = new ArrayList<>();
        int count = 0;
        for (FundPosition fundPosition : fundPositionList) {
            if (transactionDate.before(fundPositionList.get(size - 1).getInitiationDate())) {
                throw new FundTransactionException(999, "redemption transaction should be after purchase and held position");
            }
            if (share.compareTo(fundPositionList.get(size - 1).getHeldShare()) > 0) {
                throw new FundTransactionException(999, "redemption share is larger than held_share in fund_position");
            }
            heldShare = heldShare.subtract(fundPosition.getHeldShare());
            ++count;
            if (heldShare.compareTo(BigDecimal.ZERO) < 0) {
                throw new FundTransactionException(999,
                    "redemption share is larger than held_share in fund_position, need to manually check fund_position and fund_transaction");
            }
            /* update held days for fund_position, 防止定时任务之后启动导致 held_days, update_date 数据不准确 */
            long heldDays = TransactionDayUtil.getHeldDays(fundPosition.getTransactionDate(), transaction.getTransactionDate());
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(transaction.getTransactionDate());
            fundPositionMapper.updateTotalAmountAndHeldDaysAndUpdateDate(fundPosition);
            if (heldShare.compareTo(BigDecimal.ZERO) == 0) {
                /* 对于赎回部分仓位, 需要更新剩余持仓的 1.total_principal_amount, 2.total_amount, 3.total_purchase_fee, 4.held_share */
                FundPosition last = fundPositionList.get(count - 1);
                for (int i = count; i < size; i++) {
                    FundPosition temp = fundPositionList.get(i);
                    temp.setTotalPrincipalAmount(temp.getTotalPrincipalAmount().subtract(last.getTotalPrincipalAmount()));
                    temp.setTotalAmount(temp.getTotalAmount().subtract(last.getTotalAmount()));
                    temp.setTotalPurchaseFee(temp.getTotalPurchaseFee().subtract(last.getTotalPurchaseFee()));
                    temp.setHeldShare(temp.getHeldShare().subtract(last.getHeldShare()));
                    fundPositionMapper.updateRemainingFundPosition(temp);
                }
                break;
            }
            Date startDate = fundPosition.getTransactionDate();
            fundPosition.setMark(DateUtil.dateToStr(startDate) + "->" + DateUtil.dateToStr(transactionDate));
            dateDeque.addFirst(startDate);
            /* set 10.status */
            if (currentDate.before(settlementDate)) {
                transaction.setStatus(FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
                fundPosition.setStatus(FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
            } else {
                transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
                fundPosition.setStatus(FundTransactionStatus.REDEEMED.getCode());
            }
            /* set 11.nav, 12.fee, 13.amount, only if nav is already updated */
            String navStr = fundHistoryNavService.selectFundHistoryNavByConditions(code, transactionDate);
            if (navStr != null && !navStr.equals("")) {
                transaction.setNav(new BigDecimal(navStr));
                List<FundRedemptionFeeRate> fundRedemptionFeeRateList =
                    fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(transaction.getCode(), transaction.getTradingPlatform());
                if (fundRedemptionFeeRateList.isEmpty()) {
                    throw new FundTransactionException(999,
                        "can't calculate redemption transaction's fee and amount, because no fee rate found according to this code and trading_platform");
                }
                Map<String, BigDecimal> map = calculateRedemptionFeeAndAmount(fundPosition, navStr, fundRedemptionFeeRateList);
                BigDecimal fee = map.get("fee");
                BigDecimal amount = map.get("amount");
                fundPosition.setTotalRedemptionFee(fee);
                fundPosition.setTotalAmount(amount);
                feeList.add(fee);
                amountList.add(amount);
            }
            /* update `fund_position` with 1.redemption_date, 2.status, 3.mark, 4.total_redemption_fee(opt), 5.total_amount(opt) */
            fundPositionMapper.updateWhenRedeemFund(fundPosition);
        }
        if (dateDeque.isEmpty()) {
            throw new FundTransactionException(999, "date deque is empty, maybe fund_position has incorrect data");
        }
        String mark = DateUtil.dateToStr(dateDeque.peekLast()) + "->" + DateUtil.dateToStr(transactionDate);
        transaction.setMark(mark);
        fundTransactionMapper.updateMarkByConditions(code, mark, dateDeque.peekLast(), transactionDate);
        if (!currentDate.before(confirmationDate)) {
            transaction.setFee(feeList.stream().reduce(BigDecimal.ZERO, BigDecimal::add));
            transaction.setAmount(amountList.stream().reduce(BigDecimal.ZERO, BigDecimal::add));
        }
        /* insert `fund_transaction` */
        fundTransactionMapper.insertFundTransaction(transaction);
    }

    /**
     * 返回 K = "fee", "amount", V = fee累加值, amount累加值 的哈希表
     *
     * @param fundPosition FundPosition
     * @param navStr       navStr
     * @param list         FundRedemptionFeeRate List
     * @return java.util.Map<java.lang.String, java.math.BigDecimal>
     * @author sichu huang
     * @date 2024/03/30
     **/
    private Map<String, BigDecimal> calculateRedemptionFeeAndAmount(FundPosition fundPosition, String navStr, List<FundRedemptionFeeRate> list) {
        Map<String, BigDecimal> map = new HashMap<>(2);
        for (int i = 0; i < list.size(); i++) {
            FundRedemptionFeeRate fundRedemptionFeeRate = list.get(i);
            String feeRate = fundRedemptionFeeRate.getFeeRate();
            if (fundPosition.getHeldDays() < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                map.put("fee", FinancialCalculationUtil.calculateRedemptionFee(fundPosition.getHeldShare(), navStr, feeRate));
                map.put("amount", FinancialCalculationUtil.calculateRedemptionAmount(fundPosition.getHeldShare(), navStr, map.get("fee")));
                break;
            }
            if (i > 0 && fundPosition.getHeldDays() >= list.get(i - 1).getFeeRateChangeDays()
                && fundPosition.getHeldDays() < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                map.put("fee", FinancialCalculationUtil.calculateRedemptionFee(fundPosition.getHeldShare(), navStr, feeRate));
                map.put("amount", FinancialCalculationUtil.calculateRedemptionAmount(fundPosition.getHeldShare(), navStr, map.get("fee")));
                break;
            }
            if (i == list.size() - 1 && fundPosition.getHeldDays() >= fundRedemptionFeeRate.getFeeRateChangeDays()) {
                feeRate = "0.00%";
                map.put("fee", FinancialCalculationUtil.calculateRedemptionFee(fundPosition.getHeldShare(), navStr, feeRate));
                map.put("amount", FinancialCalculationUtil.calculateRedemptionAmount(fundPosition.getHeldShare(), navStr, map.get("fee")));
                break;
            }
        }
        return map;
    }

    @Override
    public void dividendFund(String code, Date applicationDate, BigDecimal dividendAmountPerShare, String tradingPlatform) {
        FundTransaction transaction = new FundTransaction();
        /* set 1.code, 2.application_date, 3.transaction_date, 4.confirmation_date, 5.settlement_date,*/
        /* 6.dividend_amount_per_share, 7.trading_platform, 8.status, 9.type */
        transaction.setCode(code);
        // TODO: 等遇到现金分红的时候看一下是当天公布当天分红还是隔一天, 还是要解析分红公告
        transaction.setApplicationDate(applicationDate);
        transaction.setTransactionDate(applicationDate);
        transaction.setConfirmationDate(applicationDate);
        transaction.setSettlementDate(applicationDate);
        transaction.setDividendAmountPerShare(dividendAmountPerShare);
        transaction.setTradingPlatform(tradingPlatform);
        transaction.setStatus(FundTransactionStatus.CASH_DIVIDEND.getCode());
        transaction.setType(FundTransactionType.DIVIDEND.getCode());
        /* set 10.amount */
        List<FundPosition> fundPositionList = fundPositionMapper.selectFundPositionWithMaxHeldShareByCode(code);
        if (fundPositionList.isEmpty()) {
            throw new FundTransactionException(999, "can't calculate dividend amount, because no held_share in fund_position");
        }
        BigDecimal heldShare = fundPositionList.get(0).getHeldShare();
        transaction.setAmount(FinancialCalculationUtil.calculateDividendAmount(heldShare, dividendAmountPerShare));
        /* insert `fund_transaction` */
        fundTransactionMapper.insertFundTransaction(transaction);
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
        List<FundPosition> fundPositionList = fundPositionMapper.selectAllFundPosition();
        for (FundPosition fundPosition : fundPositionList) {
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
                insertFundPositionByFundTransaction(transaction);
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
