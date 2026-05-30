package cn.sichu.cls.component;

import lombok.extern.slf4j.Slf4j;
import org.apache.commons.codec.digest.DigestUtils;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.Map;
import java.util.stream.Collectors;

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

    // public Mono<String> fetchTelegraphList() {
    //     MultiValueMap<String, String> params = new LinkedMultiValueMap<>();
    //     params.add("app_name", "investment-tool");
    //     params.add("os", "web");
    //     params.add("sv", "8.4.6");
    //     String sign = generateSignForMultiValueMap(params);
    //     params.add("sign", sign);
    //
    //     String queryString = params.entrySet().stream().map(
    //         entry -> entry.getKey() + "=" + String.join("&" + entry.getKey() + "=",
    //             entry.getValue())).collect(Collectors.joining("&"));
    //     String fullUrl = "https://www.cls.cn/nodeapi/updateTelegraphList?" + queryString;
    //     log.info("即将请求 CLS 电报接口: {}", fullUrl);
    //
    //     return webClient.get().uri(
    //             uriBuilder -> uriBuilder.path("/nodeapi/updateTelegraphList").queryParams(params)
    //                 .build()).header("User-Agent",
    //             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    //         .header("Referer", "https://www.cls.cn/")
    //         .header("Accept", "application/json, text/plain, */*")
    //         .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
    //         .header("Accept-Encoding", "gzip, deflate, br").header("Sec-Fetch-Site", "same-origin")
    //         .header("Sec-Fetch-Mode", "cors").header("Sec-Fetch-Dest", "empty")
    //         .header("Connection", "keep-alive").retrieve().bodyToMono(String.class)
    //         .timeout(Duration.ofSeconds(10))
    //         .doOnSuccess(response -> log.debug("成功获取 CLS 电报数据，长度: {}", response.length()))
    //         .doOnError(e -> log.error("获取 CLS 电报失败", e));
    // }

    /**
     * update 2026/05/30: 从2025/05/29开始404无法访问原接口<a href="https://www.cls.cn/nodeapi/updateTelegraphList">...</a>
     *
     * @return reactor.core.publisher.Mono<java.lang.String>
     * @author sichu huang
     * @since 2026/05/30 08:30:16
     */
    public Mono<String> fetchTelegraphList() {
        MultiValueMap<String, String> params = new LinkedMultiValueMap<>();
        params.add("app", "CailianpressWeb");
        params.add("name", "telegraph");
        params.add("os", "web");
        params.add("sv", "8.7.9");

        String sign = generateSign(params);
        params.add("sign", sign);

        String queryString = params.entrySet().stream().map(
            entry -> entry.getKey() + "=" + String.join("&" + entry.getKey() + "=",
                entry.getValue())).collect(Collectors.joining("&"));

        String fullUrl = "https://www.cls.cn/api/cache?" + queryString;
        log.info("即将请求 CLS 电报接口: {}", fullUrl);

        return webClient.get()
            .uri(uriBuilder -> uriBuilder.path("/api/cache").queryParams(params).build())
            .header("User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            .header("Referer", "https://www.cls.cn/")
            .header("Accept", "application/json, text/plain, */*").retrieve()
            .bodyToMono(String.class).timeout(Duration.ofSeconds(10))
            .doOnSuccess(response -> log.debug("成功获取 CLS 电报数据，长度: {}", response.length()))
            .doOnError(e -> log.error("获取 CLS 电报失败", e));
    }

    /**
     * MD5做key=value
     *
     * @param params params
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/05/30 08:37:55
     */
    private String generateSign(MultiValueMap<String, String> params) {
        String sortedParams = params.entrySet().stream().sorted(Map.Entry.comparingByKey())
            .map(entry -> entry.getKey() + "=" + entry.getValue().get(0))
            .collect(Collectors.joining("&"));

        return DigestUtils.md5Hex(sortedParams);
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
                /* 返回空数组, 由调用方判断 */
                return Mono.just(new byte[0]);
            });
    }

    /**
     * 将 MultiValueMap 转为排序后的 k=v 字符串, 每个 key 只取第一个值
     * <p/>
     * 先SHA1, 再MD5
     *
     * @param params params
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/14 13:39:51
     */
    // private String generateSignForMultiValueMap(MultiValueMap<String, String> params) {
    //     String sortedParams = params.entrySet().stream().sorted(Map.Entry.comparingByKey())
    //         .map(entry -> entry.getKey() + "=" + entry.getValue().get(0))
    //         .collect(Collectors.joining("&"));
    //     String sha1 = DigestUtils.sha1Hex(sortedParams);
    //     return DigestUtils.md5Hex(sha1);
    // }
}
