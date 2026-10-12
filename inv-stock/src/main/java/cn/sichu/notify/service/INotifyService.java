package cn.sichu.notify.service;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
public interface INotifyService {

    /**
     * 异步推送一条消息给用户(hermes send → 微信), 不阻塞调用方; 未配置 hermes 时只打日志
     * iLink 有频控, 失败间隔 60s 重试, 最多 3 次
     *
     * @author sichu huang
     * @param message message
     * @since 2026/10/12
     **/
    void sendAsync(String message);
}
