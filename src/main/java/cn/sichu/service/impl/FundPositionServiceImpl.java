package cn.sichu.service.impl;

import cn.sichu.mapper.FundPositionMapper;
import cn.sichu.service.IFundPositionService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * @author sichu huang
 * @date 2024/03/16
 **/
@Service
public class FundPositionServiceImpl implements IFundPositionService {
    @Autowired
    private FundPositionMapper fundPositionMapper;
}
