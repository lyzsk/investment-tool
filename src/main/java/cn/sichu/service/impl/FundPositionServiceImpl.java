package cn.sichu.service.impl;

import cn.sichu.entity.FundPosition;
import cn.sichu.entity.FundPurchaseTransaction;
import cn.sichu.enums.FundTransactionStatus;
import cn.sichu.mapper.FundPositionMapper;
import cn.sichu.service.IFundPositionService;
import cn.sichu.utils.TransactionDayUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.*;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
@Service
public class FundPositionServiceImpl implements IFundPositionService {
    @Autowired
    FundPositionMapper fundPositionMapper;
    @Autowired
    FundTransactionServiceImpl fundTransactionService;

    /**
     * @author sichu huang
     * @date 2024/03/17
     **/
    @Override
    public void insertFundPosition() throws ParseException {
        List<FundPurchaseTransaction> purchaseTransactions = fundTransactionService.selectAllFundPurchaseTransactions();
        Map<String, FundPosition> map = new HashMap<>();
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd");
        for (FundPurchaseTransaction transaction : purchaseTransactions) {
            if (!Objects.equals(transaction.getStatus(), FundTransactionStatus.HELD.getCode())) {
                continue;
            }
            String code = transaction.getCode();
            FundPosition fundPosition = map.get(code);
            if (fundPosition == null) {
                fundPosition = new FundPosition();
                fundPosition.setCode(code);
                fundPosition.setTotalAmount(String.valueOf(new BigDecimal("0.00")));
                fundPosition.setTotalPurchaseFee(String.valueOf(new BigDecimal("0.00")));
                fundPosition.setHeldShare(String.valueOf(new BigDecimal("0.00")));
                map.put(code, fundPosition);
            }
            fundPosition.setTransactionDate(transaction.getTransactionDate());
            fundPosition.setInitiationDate(transaction.getSettlementDate());
            BigDecimal totalAmount = new BigDecimal(fundPosition.getTotalAmount());
            BigDecimal totalPurchaseFee = new BigDecimal(fundPosition.getTotalPurchaseFee());
            BigDecimal heldShare = new BigDecimal(fundPosition.getHeldShare());
            totalAmount = totalAmount.add(new BigDecimal(transaction.getAmount()));
            totalPurchaseFee = totalPurchaseFee.add(new BigDecimal(transaction.getFee()));
            heldShare = heldShare.add(new BigDecimal(transaction.getShare()));
            fundPosition.setTotalAmount(String.valueOf(totalAmount));
            fundPosition.setTotalPurchaseFee(String.valueOf(totalPurchaseFee));
            fundPosition.setHeldShare(String.valueOf(heldShare));
            long heldDays = TransactionDayUtil.getHeldDays(new Date(), transaction.getTransactionDate());
            fundPosition.setHeldDays((int)heldDays);
            fundPosition.setUpdateDate(sdf.parse(sdf.format(new Date())));
            map.put(code, fundPosition);
            fundPositionMapper.insertFundPosition(fundPosition);
        }
    }
}