package cn.sichu.service.impl;

import cn.sichu.entity.FundPosition;
import cn.sichu.entity.FundPurchaseTransaction;
import cn.sichu.mapper.FundPositionMapper;
import cn.sichu.service.IFundPositionService;
import cn.sichu.utils.DateUtil;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.text.ParseException;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
@Service
public class FundPositionServiceImpl implements IFundPositionService {
    @Autowired
    FundPositionMapper fundPositionMapper;

    /**
     * @param purchaseTransactions purchaseTransactions
     * @author sichu huang
     * @date 2024/03/19
     **/
    @Override
    public void insertFundPosition(List<FundPurchaseTransaction> purchaseTransactions) throws ParseException {
        Map<String, FundPosition> map = new HashMap<>();
        for (FundPurchaseTransaction transaction : purchaseTransactions) {
            String code = transaction.getCode();
            FundPosition fundPosition = map.get(code);
            if (fundPosition == null) {
                fundPosition = new FundPosition();
                fundPosition.setCode(code);
                fundPosition.setTotalAmount(new BigDecimal("0.00"));
                fundPosition.setTotalPurchaseFee(new BigDecimal("0.00"));
                fundPosition.setHeldShare(new BigDecimal("0.00"));
                map.put(code, fundPosition);
            }
            fundPosition.setTransactionDate(transaction.getTransactionDate());
            fundPosition.setInitiationDate(transaction.getSettlementDate());
            BigDecimal totalAmount = fundPosition.getTotalAmount();
            BigDecimal totalPurchaseFee = fundPosition.getTotalPurchaseFee();
            BigDecimal heldShare = fundPosition.getHeldShare();
            totalAmount = totalAmount.add(transaction.getAmount());
            totalPurchaseFee = totalPurchaseFee.add(transaction.getFee());
            heldShare = heldShare.add(transaction.getShare());
            fundPosition.setTotalAmount(totalAmount);
            fundPosition.setTotalPurchaseFee(totalPurchaseFee);
            fundPosition.setHeldShare(heldShare);
            Date currentDate = new Date();
            long heldDays = TransactionDayUtil.getHeldDays(currentDate, transaction.getTransactionDate());
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(DateUtil.formatDate(currentDate));
            map.put(code, fundPosition);
            fundPositionMapper.insertFundPosition(fundPosition);

            // Date settlementDate = transaction.getSettlementDate();
            // long settledDays = TransactionDayUtil.getHeldDays(currentDate, settlementDate);
            // while (settledDays > 0) {
            //     --heldDays;
            //     currentDate = new Date(currentDate.getTime() - 24 * 60 * 60 * 1000L);
            //     fundPosition.setHeldDays((int)heldDays);
            //     fundPosition.setUpdateDate(currentDate);
            //     fundPositionMapper.insertFundPosition(fundPosition);
            //     --settledDays;
            // }
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
}