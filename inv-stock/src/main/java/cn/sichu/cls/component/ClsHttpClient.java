package cn.sichu.cls.component;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;

/**
 * <a href="https://www.cls.cn/nodeapi/updateTelegraphList">电报json</a>
 * <a href="https://www.cls.cn/detail/cls_id">电报detail</a>
 *
 * @author sichu huang
 * @since 2026/01/03 16:31
 */
@Component
@Slf4j
public class ClsHttpClient {
    private final WebClient webClient;

    public ClsHttpClient() {
        this.webClient = WebClient.builder().baseUrl("https://www.cls.cn")
            .codecs(configurer -> configurer.defaultCodecs().maxInMemorySize(10 * 1024 * 1024))
            .build();
    }

    public Mono<String> fetchTelegraphList() {
        return webClient.get().uri("/nodeapi/updateTelegraphList")
            .accept(MediaType.APPLICATION_JSON).retrieve().bodyToMono(String.class)
            .timeout(Duration.ofSeconds(10))
            .doOnSuccess(response -> log.debug("成功获取 CLS 电报数据，长度: {}", response.length()))
            .doOnError(e -> log.error("获取 CLS 电报失败", e));
    }

    /**
     * 下载图片为 byte[]
     *
     * @param url url
     * @return reactor.core.publisher.Mono<byte [ ]> 图片二进制数据
     * @author sichu huang
     * @since 2026/01/03 18:28:36
     */
    public Mono<byte[]> downloadImage(String url) {
        return webClient.get().uri(url)
            .accept(MediaType.IMAGE_JPEG, MediaType.IMAGE_PNG, MediaType.IMAGE_GIF, MediaType.ALL)
            .retrieve().bodyToMono(byte[].class).timeout(Duration.ofSeconds(30))
            .onErrorResume(e -> {
                log.warn("下载图片失败: {} | 原因: {}", url, e.getMessage());
                return Mono.just(new byte[0]); // 返回空数组，由调用方判断
            });
    }
}
