package cn.sichu;

import config.ProjectConfig;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

/**
 * @author sichu huang
 * @since 2025/11/08 14:21
 */
@SpringBootApplication(scanBasePackages = "cn.sichu")
@MapperScan(basePackages = {"cn.sichu.**.mapper"})
@EnableConfigurationProperties({ProjectConfig.class})
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
