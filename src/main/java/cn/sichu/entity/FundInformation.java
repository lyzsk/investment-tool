package cn.sichu.entity;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public class FundInformation {
    private Long id;
    private String code;
    private String shortName;
    private String fullName;
    private String companyName;
    private Integer purchaseConfirmationProcess;
    private Integer redemptionConfirmationProcess;
    private Integer redemptionSettlementProcess;

    public FundInformation() {
    }

    public FundInformation(Long id, String code, String shortName, String fullName, String companyName, Integer purchaseConfirmationProcess,
        Integer redemptionConfirmationProcess, Integer redemptionSettlementProcess) {
        this.id = id;
        this.code = code;
        this.shortName = shortName;
        this.fullName = fullName;
        this.companyName = companyName;
        this.purchaseConfirmationProcess = purchaseConfirmationProcess;
        this.redemptionConfirmationProcess = redemptionConfirmationProcess;
        this.redemptionSettlementProcess = redemptionSettlementProcess;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("id", getId()).append("code", getCode())
            .append("shortName", getShortName()).append("fullName", getFullName()).append("companyName", getCompanyName())
            .append("purchaseConfirmationProcess", getPurchaseConfirmationProcess())
            .append("redemptionConfirmationProcess", getRedemptionConfirmationProcess())
            .append("redemptionSettlementProcess", getRedemptionSettlementProcess()).toString();
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

    public String getFullName() {
        return fullName;
    }

    public void setFullName(String fullName) {
        this.fullName = fullName;
    }

    public String getCompanyName() {
        return companyName;
    }

    public void setCompanyName(String companyName) {
        this.companyName = companyName;
    }

    public Integer getPurchaseConfirmationProcess() {
        return purchaseConfirmationProcess;
    }

    public void setPurchaseConfirmationProcess(Integer purchaseConfirmationProcess) {
        this.purchaseConfirmationProcess = purchaseConfirmationProcess;
    }

    public Integer getRedemptionConfirmationProcess() {
        return redemptionConfirmationProcess;
    }

    public void setRedemptionConfirmationProcess(Integer redemptionConfirmationProcess) {
        this.redemptionConfirmationProcess = redemptionConfirmationProcess;
    }

    public Integer getRedemptionSettlementProcess() {
        return redemptionSettlementProcess;
    }

    public void setRedemptionSettlementProcess(Integer redemptionSettlementProcess) {
        this.redemptionSettlementProcess = redemptionSettlementProcess;
    }
}
