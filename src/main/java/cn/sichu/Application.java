package cn.sichu;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
// @SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})
@SpringBootApplication
@EnableScheduling
@ComponentScan({"cn.sichu.*"})
@MapperScan("cn.sichu.mapper")
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
        System.out.println("  ___                     _                        _     _____           _ ");
        System.out.println(" |_ _|_ ____   _____  ___| |_ _ __ ___   ___ _ __ | |_  |_   _|__   ___ | |");
        System.out.println("  | || '_ \\ \\ / / _ \\/ __| __| '_ ` _ \\ / _ \\ '_ \\| __|   | |/ _ \\ / _ \\| |");
        System.out.println("  | || | | \\ V /  __/\\__ \\ |_| | | | | |  __/ | | | |_    | | (_) | (_) | |");
        System.out.println(" |___|_| |_|\\_/ \\___||___/\\__|_| |_| |_|\\___|_| |_|\\__|   |_|\\___/ \\___/|_|\n");
        System.out.println(" Author: Sichu Huang                 Github: lyzsk                 (v1.1.5)\n");
        System.out.println(" =========================== Start Successfully! ===========================\n");
    }
}
