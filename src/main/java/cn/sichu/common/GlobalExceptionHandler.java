package cn.sichu.common;

import cn.sichu.exception.ExcelException;
import cn.sichu.exception.FundTransactionException;
import org.springframework.util.StringUtils;
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
        if (e instanceof FundTransactionException fundTransactionException) {
            return Resp.error(fundTransactionException.getCode(), fundTransactionException.getMessage());
        }
        if (e instanceof ExcelException excelException) {
            return Resp.error(excelException.getCode(), excelException.getMessage());
        }
        return Resp.error(500, StringUtils.hasLength(e.getMessage()) ? e.getMessage() : "unknown exception");
    }
}
