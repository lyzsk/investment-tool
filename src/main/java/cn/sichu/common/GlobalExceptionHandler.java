package cn.sichu.common;

import cn.sichu.exception.FundTransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * RestControllerAdvice = @ControllerAdvice + @ResponseBody
 *
 * @author sichu huang
 * @date 2024/03/24
 **/
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(value = Exception.class)
    public <T> Resp<T> exceptionHandler(Exception e) {
        if (e instanceof FundTransactionException) {
            FundTransactionException fundTransactionException = (FundTransactionException)e;
            return Resp.error(fundTransactionException.getCode(), fundTransactionException.getMessage());
        }
        return Resp.error(500, e.getMessage());
    }
}
