package cn.sichu.service.impl;

import cn.sichu.entity.GoldPosition;
import cn.sichu.entity.GoldTransaction;
import cn.sichu.enums.AppExceptionCodeMsg;
import cn.sichu.enums.GoldTransactionType;
import cn.sichu.exception.TransactionException;
import cn.sichu.mapper.GoldPositionMapper;
import cn.sichu.mapper.GoldTransactionMapper;
import cn.sichu.service.IGoldTransactionService;
import cn.sichu.utils.DateTimeUtil;
import cn.sichu.utils.FinancialCalculationUtil;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.util.List;

/**
 * @author sichu huang
 * @date 2024/06/10
 **/
@Service
public class GoldTransactionServiceImpl implements IGoldTransactionService {
    @Autowired
    GoldTransactionMapper goldTransactionMapper;
    @Autowired
    GoldPositionMapper goldPositionMapper;

    @Override
    public void purchaseGold(String pricePerGram, String grams, String transactionTime, String tradingPlatform) throws IOException {
        GoldTransaction transaction =
            new GoldTransaction(new BigDecimal(pricePerGram), new BigDecimal(grams), DateTimeUtil.strToDateTime(transactionTime),
                tradingPlatform);
        transaction.setType(GoldTransactionType.PURCHASE.getCode());
        goldTransactionMapper.insertGoldTransaction(transaction);
        handleGoldPosition(transaction);
    }

    @Override
    public void redeemGold(String pricePerGram, String grams, String transactionTime, String tradingPlatform) throws IOException {
        GoldTransaction transaction =
            new GoldTransaction(new BigDecimal(pricePerGram), new BigDecimal(grams), DateTimeUtil.strToDateTime(transactionTime),
                tradingPlatform);
        transaction.setType(GoldTransactionType.REDEMPTION.getCode());
        List<GoldPosition> positionList = goldPositionMapper.selectGoldPositionWithNullMark();
        if (positionList.isEmpty()) {
            throw new TransactionException(AppExceptionCodeMsg.GOLD_TRANSACTION_EXCEPTION.getCode(),
                "nothing to redeem, because no gold position found");
        }
        String mark = DateTimeUtil.dateTimeToStr(positionList.get(0).getPurchaseTime()) + "->" + transactionTime;
        transaction.setMark(mark);
        goldTransactionMapper.insertGoldTransaction(transaction);
        handleGoldPosition(transaction);
    }

    /**
     * @param transaction GoldTransaction
     * @author sichu huang
     * @date 2024/06/10
     **/
    private void handleGoldPosition(GoldTransaction transaction) throws IOException {
        if (transaction.getType().equals(GoldTransactionType.PURCHASE.getCode())) {
            GoldPosition position = new GoldPosition();
            position.setTradingPlatform(transaction.getTradingPlatform());
            position.setPurchaseTime(transaction.getTransactionTime());
            List<GoldPosition> positionList = goldPositionMapper.selectGoldPositionWithNullMark();
            if (positionList.isEmpty()) {
                position.setTotalGrams(transaction.getGrams());
                position.setTotalPrincipalAmount(
                    FinancialCalculationUtil.calculateGoldTransactionAmount(transaction.getPricePerGram(), transaction.getPricePerGram()));
                position.setAvgPricePerGram(
                    FinancialCalculationUtil.calculateAvgPricePerGram(position.getTotalPrincipalAmount(), transaction.getGrams()));
                goldPositionMapper.insertGoldPosition(position);
            } else {
                if (position.getPurchaseTime().isBefore(positionList.get(0).getPurchaseTime())) {
                    position.setTotalGrams(transaction.getGrams());
                    position.setTotalPrincipalAmount(
                        FinancialCalculationUtil.calculateGoldTransactionAmount(transaction.getPricePerGram(), transaction.getPricePerGram()));
                } else {
                    GoldPosition lastPosition = goldPositionMapper.selectLastGoldPosition(position).get(0);
                    position.setTotalGrams(transaction.getGrams().add(lastPosition.getTotalGrams()));
                    position.setTotalPrincipalAmount(
                        FinancialCalculationUtil.calculateGoldTransactionAmount(transaction.getPricePerGram(), transaction.getPricePerGram())
                            .add(lastPosition.getTotalPrincipalAmount()));
                }
                position.setAvgPricePerGram(
                    FinancialCalculationUtil.calculateAvgPricePerGram(position.getTotalPrincipalAmount(), transaction.getGrams()));
                goldPositionMapper.insertGoldPosition(position);
                updateLaterPositions(position);
            }
            updateHeldDays();
        } else {
            List<GoldPosition> positionList = goldPositionMapper.selectGoldPositionWithNullMark();
            if (positionList.isEmpty()) {
                throw new TransactionException(AppExceptionCodeMsg.GOLD_TRANSACTION_EXCEPTION.getCode(), "no gold position found to redeem");
            }
            for (GoldPosition position : positionList) {
                updateHeldDays();
                position.setRedemptionTime(transaction.getTransactionTime());
                position.setTotalAmount(
                    FinancialCalculationUtil.calculateGoldTransactionAmount(transaction.getGrams(), transaction.getPricePerGram()));
                position.setMark(transaction.getMark());
                goldPositionMapper.updateGoldPositionWhenRedeem(position);
            }
        }
    }

    /**
     * @param goldPosition goldPosition
     * @author sichu huang
     * @date 2024/06/10
     **/
    private void updateLaterPositions(GoldPosition goldPosition) {
        List<GoldPosition> laterPositionList = goldPositionMapper.selectGoldPositionAfterDateTime(goldPosition);
        for (GoldPosition position : laterPositionList) {
            position.setTotalGrams(goldPosition.getTotalGrams().add(position.getTotalGrams()));
            position.setTotalPrincipalAmount(goldPosition.getTotalPrincipalAmount().add(position.getTotalPrincipalAmount()));
            position.setTotalAmount(goldPosition.getTotalAmount().add(position.getTotalAmount()));
            position.setAvgPricePerGram(FinancialCalculationUtil.calculateAvgPricePerGram(position.getTotalAmount(), position.getTotalGrams()));
            goldPositionMapper.updateGoldPositionWhenPurchase(position);
        }
    }

    @Override
    public void updateHeldDays() throws IOException {
        List<GoldPosition> positionList = goldPositionMapper.selectGoldPositionWithNullMark();
        for (GoldPosition position : positionList) {
            int heldDays = TransactionDayUtil.getHeldTransactionDays(position.getPurchaseTime(), position.getRedemptionTime());
            position.setHeldDays(heldDays);
            goldPositionMapper.updateHeldDays(position);
        }
    }
}
