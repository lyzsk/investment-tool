package cn.sichu.entity;

/**
 * https://fundf10.eastmoney.com/jjjz_{code}.html
 *
 * @author sichu huang
 * @date 2024/03/18
 **/
public class FundEastmoneyJjjz {
    private Long id;
    private String code;
    private String callback;

    public FundEastmoneyJjjz() {
    }

    public FundEastmoneyJjjz(Long id, String code, String callback) {
        this.id = id;
        this.code = code;
        this.callback = callback;
    }

    @Override
    public String toString() {
        return "FundEastmoneyJjjz{" + "id=" + id + ", code='" + code + '\'' + ", callback='" + callback + '\'' + '}';
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getCallback() {
        return callback;
    }

    public void setCallback(String callback) {
        this.callback = callback;
    }
}
