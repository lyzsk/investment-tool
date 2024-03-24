package cn.sichu.common;

import cn.sichu.exception.FundTransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.HashMap;
import java.util.Map;

/**
 * RestControllerAdvice = @ControllerAdvice + @ResponseBody
 *
 * @author sichu huang
 * @date 2024/03/24
 **/
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(value = FundTransactionException.class)
    public Map<String, Object> fundTransactionHandler(FundTransactionException e) {
        Map<String, Object> map = new HashMap<>();
        map.put("code", e.getCode());
        map.put("meesage", e.getMessage());
        return map;
    }
}
