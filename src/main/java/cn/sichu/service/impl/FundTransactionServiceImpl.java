package cn.sichu.service.impl;

import cn.sichu.entity.*;
import cn.sichu.enums.FundTransactionStatus;
import cn.sichu.enums.FundTransactionType;
import cn.sichu.exception.FundTransactionException;
import cn.sichu.mapper.FundPositionMapper;
import cn.sichu.mapper.FundPurchaseFeeRateMapper;
import cn.sichu.mapper.FundRedemptionFeeRateMapper;
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
    FundPurchaseFeeRateMapper fundPurchaseFeeRateMapper;
    @Autowired
    FundRedemptionFeeRateMapper fundRedemptionFeeRateMapper;
    @Autowired
    FundPositionMapper fundPositionMapper;

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
        int status;
        if (currentDate.before(settlementDate)) {
            status = FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode();
        } else {
            status = FundTransactionStatus.HELD.getCode();
        }
        transaction.setStatus(status);
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
        String navStr = fundHistoryNavService.selectFundNavByConditions(code, transactionDate);
        if (navStr != null && !navStr.equals("")) {
            transaction.setNav(new BigDecimal(navStr));
            transaction.setShare(FinancialCalculationUtil.calculateShare(amount, transaction.getFee(), navStr));
            /* insert `fund_position` */
            if (Objects.equals(status, FundTransactionStatus.HELD.getCode())) {
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
     * 13.trading_platform, 14.status, 15.mark
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
        /* set 1.code, 2.transaction_date, 3.initiation_date, 4.held_days, 5.update_date, 6.trading_platform, 7.status */
        fundPosition.setCode(code);
        fundPosition.setTransactionDate(transactionDate);
        fundPosition.setInitiationDate(initiationDate);
        Date currentDate = new Date();
        long heldDays = TransactionDayUtil.getHeldTransactionDays(currentDate, transaction.getTransactionDate());
        fundPosition.setHeldDays((int)heldDays);
        fundPosition.setUpdateDate(currentDate);
        fundPosition.setTradingPlatform(transaction.getTradingPlatform());
        fundPosition.setStatus(transaction.getStatus());
        /* set 8.total_principal_amount, 9.total_purchase_fee, 10.held_share, 11.total_amount */
        List<FundPosition> fundPositionList = fundPositionMapper.selectFundPositionWithNullMarkByCode(code);
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
        String navStr = fundHistoryNavService.selectFundNavByConditions(fundPosition.getCode(), lastNTransactionDate);
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
        List<FundPosition> fundPositionList = fundPositionMapper.selectFundPositionWithNullMarkByCode(code);
        if (fundPositionList.isEmpty()) {
            throw new FundTransactionException(999, "nothing to redeem, because no fund position found by code");
        }
        int size = fundPositionList.size();
        Date startDate = fundPositionList.get(0).getTransactionDate();
        /* set 9.mark, 在 `fund_transaction` 中为一条 redemption */
        String mark = DateUtil.dateToStr(startDate) + "->" + DateUtil.dateToStr(transactionDate);
        transaction.setMark(mark);
        BigDecimal fee = null;
        BigDecimal amount = null;
        int count = 0;
        for (FundPosition fundPosition : fundPositionList) {
            if (transactionDate.before(fundPositionList.get(size - 1).getInitiationDate())) {
                throw new FundTransactionException(999, "redemption transaction should be after purchase and held position");
            }
            if (share.compareTo(fundPositionList.get(size - 1).getHeldShare()) > 0) {
                throw new FundTransactionException(999, "redemption share is larger than held_share in fund_position");
            }
            BigDecimal tempShare = new BigDecimal(String.valueOf(share)).subtract(fundPosition.getHeldShare());
            ++count;
            /* 目前仅支持每笔 fund_position 满份额赎回 */
            if (tempShare.compareTo(BigDecimal.ZERO) < 0) {
                break;
            }
            /* update held days for fund_position, 防止首次记录并未执行定时任务时 held_days, update_date 数据不准确 */
            long heldDays = TransactionDayUtil.getHeldDays(fundPosition.getTransactionDate(), transaction.getTransactionDate());
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(transaction.getTransactionDate());
            fundPositionMapper.updateHeldDaysAndUpdateDate(fundPosition);
            /* set 9.mark, 在 `fund_position` 中为n条 redemption, (仅考虑每笔交易满份额赎回) */
            fundPosition.setMark(DateUtil.dateToStr(fundPosition.getTransactionDate()) + "->" + DateUtil.dateToStr(transactionDate));
            fundPosition.setRedemptionDate(transactionDate);
            /* set 10.status */
            if (currentDate.before(settlementDate)) {
                transaction.setStatus(FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
                fundPosition.setStatus(FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
            } else {
                transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
                fundPosition.setStatus(FundTransactionStatus.REDEEMED.getCode());
            }
            /* set 11.nav, 12.fee, 13.amount, only if nav is already updated */
            String navStr = fundHistoryNavService.selectFundNavByConditions(code, transactionDate);
            if (navStr != null && !navStr.equals("")) {
                transaction.setNav(new BigDecimal(navStr));
                List<FundRedemptionFeeRate> fundRedemptionFeeRateList =
                    fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(transaction.getCode(), transaction.getTradingPlatform());
                if (fundRedemptionFeeRateList.isEmpty()) {
                    throw new FundTransactionException(999,
                        "can't calculate redemption transaction's fee and amount, because no fee rate found according to this code and trading_platform");
                }
                Map<String, BigDecimal> map = calculateRedemptionFeeAndAmount(fundPosition, navStr, fundRedemptionFeeRateList);
                BigDecimal totalRedemptionFee = map.get("fee");
                BigDecimal totalAmount = map.get("amount");
                fundPosition.setTotalRedemptionFee(totalRedemptionFee);
                fundPosition.setTotalAmount(totalAmount);
                fee = totalRedemptionFee;
                amount = totalAmount;
            }
            if (tempShare.compareTo(BigDecimal.ZERO) == 0) {
                /* 对于赎回部分仓位, 需要更新剩余持仓的 1.total_principal_amount, 2.held_share 3.total_purchase_fee */
                List<FundPosition> remainingList = fundPositionList.subList(count, size);
                for (FundPosition item : remainingList) {
                    item.setTotalPrincipalAmount(item.getTotalPrincipalAmount().subtract(fundPosition.getTotalPrincipalAmount()));
                    item.setHeldShare(item.getHeldShare().subtract(fundPosition.getHeldShare()));
                    item.setTotalPurchaseFee(item.getTotalPurchaseFee().subtract(fundPosition.getTotalPurchaseFee()));
                    fundPositionMapper.updateRemainingFundPosition(item);
                }
            }
            /* update `fund_position` with 1.redemption_date, 2.status, 3.mark, 4.total_redemption_fee(opt), 5.total_amount(opt) */
            fundPositionMapper.updateWhenRedeemFund(fundPosition);
        }
        // TODO: 对部分赎回好像这里有误, 应该根据count?
        fundTransactionMapper.updateMarkByConditions(code, mark, startDate, transactionDate);
        if (currentDate.compareTo(confirmationDate) >= 0 && fee != null && amount != null) {
            transaction.setFee(fee);
            transaction.setAmount(amount);
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
        Integer type = FundTransactionType.DIVIDEND.getCode();
        transaction.setType(type);
        /* set 10.amount */
        List<FundPosition> fundPositionList = fundPositionMapper.selectFundPositionWithMaxHeldShareByConditions(code, type);
        if (fundPositionList.isEmpty()) {
            throw new FundTransactionException(999, "can't calculate dividend amount, because no held_share in fund_position");
        }
        BigDecimal heldShare = fundPositionList.get(0).getHeldShare();
        transaction.setAmount(FinancialCalculationUtil.calculateDividendAmount(heldShare, dividendAmountPerShare));
        /* insert `fund_transaction` */
        fundTransactionMapper.insertFundTransaction(transaction);
    }

    @Override
    public void dailyUpdateFundTransactionAndFundPosition() throws ParseException, IOException {
        Date date = new Date();
        /* i. purchase transaction: update 1.nav, 2.share 3.status(opt) for `fund_transaction`; update 1.total_amount for `fund_position` */
        List<FundTransaction> purchaseTransactionList =
            fundTransactionMapper.selectAllPurchaseTransactionWithNullNavAndShare(FundTransactionType.PURCHASE.getCode());
        for (FundTransaction transaction : purchaseTransactionList) {
            if (date.before(transaction.getConfirmationDate())) {
                continue;
            }
            String navStr = fundHistoryNavService.selectFundNavByConditions(transaction.getCode(), transaction.getTransactionDate());
            if (navStr == null || navStr.equals("")) {
                continue;
            }
            transaction.setNav(new BigDecimal(navStr));
            transaction.setShare(FinancialCalculationUtil.calculateShare(transaction.getAmount(), transaction.getFee(), navStr));
            fundTransactionMapper.updateNavAndShare(transaction);
            List<FundPosition> fundPositionList = fundPositionMapper.selectFundPositionByPurchaseTransaction(transaction);
            for (FundPosition fundPosition : fundPositionList) {
                fundPosition.setTotalAmount(FinancialCalculationUtil.calculateTotalAmount(fundPosition.getHeldShare(), navStr));
                fundPositionMapper.updateTotalAmount(fundPosition);
            }
        }
        /* ii. redemption transaction: update 1.amount, 2.fee, 3.nav for `fund_transaction`; update 1.total_amount, 2.total_redemption_fee for `fund_position` */
        List<FundPosition> fundPositionList = fundPositionMapper.selectAllFundPositionWithNullTotalAmountAndTotalRedemptionFee();
        // TODO: 研究capability设大还是设小好, 因为key是code, capability 肯定不满 fundPositionList.size()
        Map<String, BigDecimal[]> map = new HashMap<>(fundPositionList.size());
        for (FundPosition fundPosition : fundPositionList) {
            String code = fundPosition.getCode();
            Date redemptionDate = fundPosition.getRedemptionDate();
            List<FundInformation> fundInformationList = fundInformationService.selectFundRedemptionTransactionProcessByCode(code);
            if (fundInformationList.isEmpty()) {
                throw new FundTransactionException(999,
                    "can't calculate redemption transaction's confirmation_date, because no fund information found by code");
            }
            FundInformation information = fundInformationList.get(0);
            Integer n = information.getRedemptionConfirmationProcess();
            Date confirmationDate = TransactionDayUtil.getNextNTransactionDate(redemptionDate, n);
            if (date.before(confirmationDate)) {
                continue;
            }
            String navStr = fundHistoryNavService.selectFundNavByConditions(code, redemptionDate);
            if (navStr == null || navStr.equals("")) {
                continue;
            }
            List<FundRedemptionFeeRate> fundRedemptionFeeRateList =
                fundRedemptionFeeRateMapper.selectRedemptionFeeRateByConditions(code, fundPosition.getTradingPlatform());
            if (fundRedemptionFeeRateList.isEmpty()) {
                throw new FundTransactionException(999,
                    "can't calculate redemption transaction's fee and amount, because no fee rate found according to this code and trading_platform");
            }
            for (int i = 0; i < fundRedemptionFeeRateList.size(); i++) {
                FundRedemptionFeeRate fundRedemptionFeeRate = fundRedemptionFeeRateList.get(i);
                String feeRate = fundRedemptionFeeRate.getFeeRate();
                if (fundPosition.getHeldDays() < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                    calculateAndUpdateTotalRedemptionFeeAndTotalAmount(fundPosition, navStr, feeRate, map);
                    break;
                }
                if (i > 0 && fundPosition.getHeldDays() >= fundRedemptionFeeRateList.get(i - 1).getFeeRateChangeDays()
                    && fundPosition.getHeldDays() < fundRedemptionFeeRate.getFeeRateChangeDays()) {
                    calculateAndUpdateTotalRedemptionFeeAndTotalAmount(fundPosition, navStr, feeRate, map);
                    break;
                }
                if (i == fundRedemptionFeeRateList.size() - 1 && fundPosition.getHeldDays() >= fundRedemptionFeeRate.getFeeRateChangeDays()) {
                    feeRate = "0.00%";
                    calculateAndUpdateTotalRedemptionFeeAndTotalAmount(fundPosition, navStr, feeRate, map);
                    break;
                }
            }
            // TODO: 存在效率问题, 因为对一个code而言有几个fund_position, 就会update一次fund_transaction, 而应该直接 update code 对应的最后一个 fund_position 即可
            List<FundTransaction> redemptionTransactionList =
                fundTransactionMapper.selectAllRedemptionFundTransactionWithNullAmountAndFeeAndNav(code, redemptionDate,
                    FundTransactionType.REDEMPTION.getCode());
            for (FundTransaction transaction : redemptionTransactionList) {
                transaction.setNav(new BigDecimal(navStr));
                transaction.setFee(map.get(code)[0]);
                transaction.setAmount(map.get(code)[1]);
                fundTransactionMapper.updateNavAndFeeAndAmount(transaction);
            }
        }
        /* update 1.total_amount for `fund_position`, mark is null and total_amount != null 代表就是HELD状态的position */
        List<FundPosition> list = fundPositionMapper.selectAllFundPositionWithNullMarkAndNotNullTotalAmount();
        for (FundPosition fundPosition : list) {
            String code = fundPosition.getCode();
            Date redemptionDate = fundPosition.getRedemptionDate();
            List<FundInformation> fundInformationList = fundInformationService.selectFundRedemptionTransactionProcessByCode(code);
            if (fundInformationList.isEmpty()) {
                throw new FundTransactionException(999,
                    "can't calculate purchase transaction's confirmation_date, because no fund information found by code");
            }
            FundInformation information = fundInformationList.get(0);
            Integer n = information.getRedemptionConfirmationProcess();
            Date confirmationDate = TransactionDayUtil.getNextNTransactionDate(redemptionDate, n);
            if (date.before(confirmationDate)) {
                continue;
            }
            String navStr = fundHistoryNavService.selectFundNavByConditions(code, redemptionDate);
            if (navStr == null || navStr.equals("")) {
                continue;
            }
            fundPosition.setTotalAmount(FinancialCalculationUtil.calculateTotalAmount(fundPosition.getHeldShare(), navStr));
            fundPositionMapper.updateTotalAmount(fundPosition);
        }
    }

    /**
     * @param fundPosition FundPosition
     * @param navStr       navStr
     * @param feeRate      feeRate
     * @param map          Key: code, Value: [redemptionFee, totalAmount]
     * @author sichu huang
     * @date 2024/04/27
     **/
    private void calculateAndUpdateTotalRedemptionFeeAndTotalAmount(FundPosition fundPosition, String navStr, String feeRate,
        Map<String, BigDecimal[]> map) {
        String code = fundPosition.getCode();
        BigDecimal heldShare = fundPosition.getHeldShare();
        BigDecimal totalRedemptionFee = FinancialCalculationUtil.calculateRedemptionFee(heldShare, navStr, feeRate);
        BigDecimal totalAmount = FinancialCalculationUtil.calculateRedemptionAmount(heldShare, navStr, totalRedemptionFee);
        map.put(code, new BigDecimal[] {totalRedemptionFee, totalAmount});
        fundPosition.setTotalRedemptionFee(totalRedemptionFee);
        fundPosition.setTotalAmount(totalAmount);
        fundPositionMapper.updateTotalRedemptionFeeAndTotalAmount(fundPosition);
    }

    @Override
    public void updateHeldDaysAndUpdateDateForFundPosition(Date date) throws ParseException {
        List<FundPosition> fundPositionList = fundPositionMapper.selectAllFundPositionWithNullMark();
        for (FundPosition fundPosition : fundPositionList) {
            Date formattedDate = DateUtil.formatDate(date);
            long heldDays = TransactionDayUtil.getHeldDays(fundPosition.getTransactionDate(), date);
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(formattedDate);
            fundPositionMapper.updateHeldDaysAndUpdateDate(fundPosition);
        }
    }

    @Override
    public void updateStatusForTransactionInTransit(Date date) throws IOException, ParseException {
        /* update `fund_transaction` */
        List<FundTransaction> fundTransactionList =
            fundTransactionMapper.selectAllFundTransactionInTransit(FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode(),
                FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
        for (FundTransaction transaction : fundTransactionList) {
            if (date.compareTo(transaction.getSettlementDate()) >= 0) {
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.PURCHASE_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.HELD.getCode());
                    fundTransactionMapper.updateStatus(transaction);
                    /* insert into `fund_position` */
                    insertFundPositionByFundTransaction(transaction);
                }
                if (Objects.equals(transaction.getStatus(), FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode())) {
                    transaction.setStatus(FundTransactionStatus.REDEEMED.getCode());
                    fundTransactionMapper.updateStatus(transaction);
                }

            }
        }
        /* update `fund_position` */
        List<FundPosition> fundPositionList =
            fundPositionMapper.selectAllFundPositionByStatus(FundTransactionStatus.REDEMPTION_IN_TRANSIT.getCode());
        for (FundPosition fundPosition : fundPositionList) {
            String mark = fundPosition.getMark();
            if (mark != null && !mark.equals("")) {
                Date redemptionDate = DateUtil.strToDate(mark.split("->")[1]);
                List<FundInformation> fundInformationList =
                    fundInformationService.selectFundRedemptionTransactionProcessByCode(fundPosition.getCode());
                if (fundInformationList.isEmpty()) {
                    throw new FundTransactionException(999,
                        "can't update fund_position's status(REDEMPTION_IN_TRANSIT), because no fund information found by code");
                }
                FundInformation information = fundInformationList.get(0);
                Integer n = information.getRedemptionSettlementProcess();
                Date settlementDate = TransactionDayUtil.getNextNTransactionDate(redemptionDate, n);
                if (date.compareTo(settlementDate) >= 0) {
                    fundPosition.setStatus(FundTransactionStatus.REDEEMED.getCode());
                    fundPositionMapper.updateStatus(fundPosition);
                }
            }
        }
    }
}
