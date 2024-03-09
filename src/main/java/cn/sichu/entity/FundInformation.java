package cn.sichu.entity;

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

    public FundInformation() {
    }

    public FundInformation(Long id, String code, String shortName, String fullName, String companyName) {
        this.id = id;
        this.code = code;
        this.shortName = shortName;
        this.fullName = fullName;
        this.companyName = companyName;
    }

    @Override
    public String toString() {
        return "FundInformation{" + "id=" + id + ", code='" + code + '\'' + ", shortName='" + shortName + '\''
            + ", fullName='" + fullName + '\'' + ", companyName='" + companyName + '\'' + '}';
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
}
