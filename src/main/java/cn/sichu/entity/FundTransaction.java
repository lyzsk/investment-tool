package cn.sichu.entity;

import java.util.Date;

/**
 * fund_transaction 表
 *
 * @author sichu huang
 * @date 2024/03/09
 **/
public class FundTransaction {
    private Long id;
    private String code;
    private String shortName;
    private Date applicationDate;
    private Date confirmationDate;
    private Date settlementDate;
    private String fee;
    private String share;
    private String nav;
    private String amount;
    private Integer type;
    private String tradingPlatform;

    public FundTransaction() {
    }

    public FundTransaction(Long id, String code, String shortName, Date applicationDate, Date confirmationDate,
        Date settlementDate, String fee, String share, String nav, String amount, Integer type,
        String tradingPlatform) {
        this.id = id;
        this.code = code;
        this.shortName = shortName;
        this.applicationDate = applicationDate;
        this.confirmationDate = confirmationDate;
        this.settlementDate = settlementDate;
        this.fee = fee;
        this.share = share;
        this.nav = nav;
        this.amount = amount;
        this.type = type;
        this.tradingPlatform = tradingPlatform;
    }

    @Override
    public String toString() {
        return "FundTransaction{" + "id=" + id + ", code='" + code + '\'' + ", shortName='" + shortName + '\''
            + ", applicationDate=" + applicationDate + ", confirmationDate=" + confirmationDate + ", settlementDate="
            + settlementDate + ", fee='" + fee + '\'' + ", share='" + share + '\'' + ", nav='" + nav + '\''
            + ", amount='" + amount + '\'' + ", type=" + type + ", tradingPlatform='" + tradingPlatform + '\'' + '}';
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

    public String getShortName() {
        return shortName;
    }

    public void setShortName(String shortName) {
        this.shortName = shortName;
    }

    public Date getApplicationDate() {
        return applicationDate;
    }

    public void setApplicationDate(Date applicationDate) {
        this.applicationDate = applicationDate;
    }

    public Date getConfirmationDate() {
        return confirmationDate;
    }

    public void setConfirmationDate(Date confirmationDate) {
        this.confirmationDate = confirmationDate;
    }

    public Date getSettlementDate() {
        return settlementDate;
    }

    public void setSettlementDate(Date settlementDate) {
        this.settlementDate = settlementDate;
    }

    public String getFee() {
        return fee;
    }

    public void setFee(String fee) {
        this.fee = fee;
    }

    public String getShare() {
        return share;
    }

    public void setShare(String share) {
        this.share = share;
    }

    public String getNav() {
        return nav;
    }

    public void setNav(String nav) {
        this.nav = nav;
    }

    public String getAmount() {
        return amount;
    }

    public void setAmount(String amount) {
        this.amount = amount;
    }

    public Integer getType() {
        return type;
    }

    public void setType(Integer type) {
        this.type = type;
    }

    public String getTradingPlatform() {
        return tradingPlatform;
    }

    public void setTradingPlatform(String tradingPlatform) {
        this.tradingPlatform = tradingPlatform;
    }
}
