package cn.sichu;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * @author sichu huang
 * @since 2025/11/08 14:21
 */
@SpringBootApplication(scanBasePackages = "cn.sichu")
@MapperScan(basePackages = {"cn.sichu.**.mapper"})
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
