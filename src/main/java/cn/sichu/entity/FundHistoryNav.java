package cn.sichu.entity;

import org.apache.commons.lang3.builder.ToStringBuilder;
import org.apache.commons.lang3.builder.ToStringStyle;

import java.util.Date;

/**
 * fund_history_nav
 *
 * @author sichu huang
 * @date 2024/03/11
 **/
public class FundHistoryNav {

    private Long id;
    private String code;
    private Date navDate;
    private String nav;

    public FundHistoryNav() {
    }

    public FundHistoryNav(Long id, String code, Date navDate, String nav) {
        this.id = id;
        this.code = code;
        this.navDate = navDate;
        this.nav = nav;
    }

    @Override
    public String toString() {
        return new ToStringBuilder(this, ToStringStyle.MULTI_LINE_STYLE).append("id", getId()).append("code", getCode())
            .append("navDate", getNavDate()).append("nav", getNav()).toString();
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

    public Date getNavDate() {
        return navDate;
    }

    public void setNavDate(Date navDate) {
        this.navDate = navDate;
    }

    public String getNav() {
        return nav;
    }

    public void setNav(String nav) {
        this.nav = nav;
    }
}
